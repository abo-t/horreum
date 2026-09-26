"""Widok Pipeline + worker `QThread` (PLAN_gui_pipeline §4/§6 — warstwa widżetów). User prowadzi
CAŁY pierwszy przebieg na własnych danych Z OKNA: wskaż katalog → skan (przyrostowy) → grupuj →
rozwiąż → kalibracja → delta — bez CLI. „Przetwórz wszystko" robi cały łańcuch jednym kliknięciem.

To JEDEN z plików warstwy widżetów, którym wolno importować PySide6 (test izolacji
`test_gui_isolation.py` — `pipeline.py` na whiteliście). Logika domenowa (skan, brama, normalizacja)
mieszka w rdzeniu Qt-wolnym (`horreum.scan`), throttle/snapshot w `horreum.gui.progress` (testowane
bez Qt). Tu zostaje sama glue: widżety, wątek, sygnały.

WSPÓŁBIEŻNOŚĆ (§4): worker otwiera WŁASNE połączenie `db.open_db` w SWOIM wątku (sqlite
`check_same_thread` — połączenie nie przechodzi między wątkami). Główny wątek NIGDY nie woła
`scan_tree` (UI się nie zamraża). Slot postępu dostaje DICT-migawkę liczników (nie żywy `ScanSummary`),
emisja przerzedzona (`progress.should_emit`). Anulowanie = `threading.Event` (stawiane w głównym
wątku przyciskiem, czytane w workerze — bezpieczne międzywątkowo)."""
import threading
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, QThread, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton,
    QVBoxLayout, QWidget,
)

from horreum import db, presence, scan
from horreum.calibration import run_calibration
from horreum.lineage import run_lineage
from horreum.gui import i18n, queries
from horreum.gui.grid import PRESET_VANISHED
from horreum.gui.progress import counts_snapshot, should_emit
from horreum.grouper import run_grouper
from horreum.resolver import delta_report, run_resolver
from horreum.scan import scan_stacks, scan_tree
from horreum.stacks import run_stack_lineage
from horreum.volumes import volume_serial


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


class PipelineWorker(QObject):
    """Wykonawca etapu pipeline'u w wątku tła. Otwiera WŁASNE połączenie (per-wątek), woła funkcję
    rdzenia, emituje sygnały. NIE dotyka widżetów (slot w głównym wątku rusza UI).

    Sygnały: `progress(done,total,path,counts:dict)` (mid-skan, DICT-migawka), `stage_done(name,
    summary)` (po etapie — `summary` już niemutowany, więc obiekt wolno przekazać), `cancelled(name,
    summary)`, `failed(name, msg)` (wyjątek → komunikat, NIE crash)."""

    progress = Signal(int, int, str, dict)
    stage_started = Signal(str)            # przed każdym (pod)etapem — UI pokazuje „… w toku"
    stage_done = Signal(str, object)       # po (pod)etapie — summary/report
    cancelled = Signal(str, object)
    failed = Signal(str, str)
    finished = Signal()                    # run() zakończył (KAŻDĄ drogą) — sygnał do quit() wątku

    def __init__(self, db_path, *, now_fn=_utc_now_iso):
        super().__init__()
        self._db_path = db_path
        self._now = now_fn
        self._cancel = threading.Event()
        self._stage = None
        self._params = {}

    def configure(self, stage, **params):
        self._stage = stage
        self._params = params

    def request_cancel(self):
        """Kooperatywne anulowanie — stawiane w GŁÓWNYM wątku, czytane w workerze (`Event` jest
        bezpieczny międzywątkowo; nie tykamy tu żadnego obiektu Qt)."""
        self._cancel.set()

    @Slot()
    def run(self):
        con = None
        try:
            con = db.open_db(self._db_path)
            if self._stage == "scan":
                self._scan(con)
            elif self._stage == "stacks":
                self._stacks(con)
            elif self._stage == "group":
                self._bulk(con, "group")
            elif self._stage == "resolve":
                self._bulk(con, "resolve")
            elif self._stage == "calibrate":
                self._bulk(con, "calibrate")
            elif self._stage == "lineage":
                self._bulk(con, "lineage")
            elif self._stage == "stack_lineage":
                # Etap ISTNIAŁ w `_bulk` od I-2c, ale nie miał własnego wejścia — leciał wyłącznie
                # jako czwarty krok drogi „Stosy". Przez to jedynym sposobem przeliczenia rodowodu
                # było ponowne wciągnięcie całego drzewa (firsthand 0808).
                self._bulk(con, "stack_lineage")
            elif self._stage == "delta":
                self._bulk(con, "delta")
            elif self._stage in ("presence", "presence-apply"):
                apply = self._stage.endswith("apply")
                s = self._presence(con, apply=apply)
                if apply and not s.cancelled and s.aborted is None:
                    self._after_vanished(con)
            elif self._stage == "all":
                self._run_all(con)
            else:
                self.failed.emit(self._stage or "?", f"nieznany etap: {self._stage!r}")
        except Exception as exc:                       # błąd etapu → sygnał, NIE crash apki
            self.failed.emit(self._stage or "?", f"{type(exc).__name__}: {exc}")
        finally:
            if con is not None:
                con.close()
            self.finished.emit()                       # zawsze: zwolnij wątek (quit pętli zdarzeń)

    def _scan(self, con):
        """Skan z progresem/anulowaniem. Zwraca summary; emituje cancelled/stage_done. `False` =
        anulowano (wołający przerywa łańcuch „all")."""
        self.stage_started.emit("scan")
        summary = scan_tree(
            con, self._params["root"],
            volume=self._params.get("volume", "?"),
            drive_letter=self._params.get("drive_letter"),
            tier=self._params.get("tier"),
            now=self._now(),
            progress=self._on_progress,
            should_cancel=self._cancel.is_set,
        )
        if summary.cancelled:
            self.cancelled.emit("scan", summary)
            return False
        self.stage_done.emit("scan", summary)
        return True

    def _stacks(self, con):
        """Droga „Stosy" (I-2b): wciągnięcie gotowych obrazów po integracji ze wskazanego drzewa
        obróbki. Kontrakt sygnałów jak w `_scan` (postęp per plik, anulowanie na granicy pliku);
        etap ŚWIADOMIE poza łańcuchem „Przyjmij nowe" — to inny korzeń i inny gest (D-P-I-1).

        DOMYKA ŁAŃCUCH (I-2d, lustro P-G na fasadzie importu): sam skan zostawiłby stosy bez osi
        (config/obiekt) i bez rodowodu, więc „wciągnąłem" znaczyłoby mniej, niż user widzi na
        ekranie. Po skanie idą więc `group` → `resolve` → **rodowód stosów** — w tej kolejności,
        bo dobór okna stoi na osi obiektu i osi teleskopu, które dopiero tamte dwa etapy powołują.
        Anulowanie skanu PRZERYWA łańcuch (jak w „Przetwórz wszystko")."""
        self.stage_started.emit("stacks")
        s = scan_stacks(
            con, self._params["root"],
            volume=self._params.get("volume", "?"),
            drive_letter=self._params.get("drive_letter"),
            tier=self._params.get("tier"),
            now=self._now(),
            progress=self._on_stack_progress,
            should_cancel=self._cancel.is_set,
        )
        if s.cancelled:
            self.cancelled.emit("stacks", s)
            return False
        self.stage_done.emit("stacks", s)
        self._bulk(con, "group")
        self._bulk(con, "resolve")
        self._bulk(con, "stack_lineage")
        return True

    def _on_stack_progress(self, done, total, path, s):
        # `scan_stacks` podaje własne summary (StackScanSummary) — migawkę robimy z ZAGNIEŻDŻONEGO
        # `ScanSummary`, bo to on niesie liczniki, które umie czytać `counts_snapshot`.
        if should_emit(done, total):
            self.progress.emit(done, total, path, counts_snapshot(s.scan))

    def _presence(self, con, *, apply):
        """Pass obecności (P5b). Etap MASOWY jak group/resolve — bez progresu per-wiersz: koszt
        siedzi w JEDNYM przejściu drzewa (~1,2 s / 15 tys. plików), którego nie da się sensownie
        pociąć. Anulowanie DZIAŁA (pętla potwierdzeń pyta `should_cancel`), więc zerwany SMB nie
        trzyma okna. `apply` NIGDY nie idzie w złotej akcji — tylko z jawnego przycisku."""
        name = "presence"
        self.stage_started.emit(name)
        s = presence.check(
            con, self._params["root"], volume=self._params.get("volume", "?"), apply=apply,
            now=self._now(), should_cancel=self._cancel.is_set)
        if s.cancelled:
            self.cancelled.emit(name, s)
        else:
            self.stage_done.emit(name, s)
        return s

    def _after_vanished(self, con):
        """Ogon gestu „Oznacz zniknięte" (AR-5): przejęcie zeznania i - gdy coś przejęto - pochodne
        (`group` → `resolve` → `calibrate` → `lineage`), w tej samej kolejności co w Dostawie.

        DLACZEGO TU, a nie dopiero w następnej dostawie: oznaczenie zniknięcia jest dokładnie tą
        chwilą, w której klatka zaczyna mówić głosem nieobecnego pliku. Bez ogona stan trwał do
        najbliższego „Przyjmij nowe" i był NIEWIDOCZNY - wiersz Porządków liczy tylko to, czego etap
        nie naprawi sam. Pochodne idą wyłącznie po realnym przejęciu: bez niego zeznania nic nie
        ruszyło, więc przeliczanie całego archiwum byłoby kosztem bez skutku. Zakres = korzeń
        zamrożony przy DRY (`root` z parametrów gestu), jak sam zapis obecności."""
        a = self._adopt_testimony(con)
        if a is None or a.cancelled or not a.adopted:
            return
        for name in ("group", "resolve", "calibrate", "lineage"):
            self._bulk(con, name)

    def _bulk(self, con, name):
        """Etap masowy (group/resolve/calibrate/lineage/delta) — bezobsługowy, sekundy–minuty, bez
        progresu per-wiersz. delta jest READ-ONLY (zero DML). Emituje stage_started → stage_done."""
        self.stage_started.emit(name)
        if name == "group":
            result = run_grouper(con, self._now())
        elif name == "resolve":
            result = run_resolver(con, self._now())
        elif name == "calibrate":
            result = run_calibration(con, now=self._now())
        elif name == "lineage":
            result = run_lineage(con, now=self._now())
        elif name == "stack_lineage":
            result = run_stack_lineage(con, now=self._now())
        else:                                          # delta — read-only
            result = delta_report(con)
        self.stage_done.emit(name, result)

    def _run_all(self, con):
        """„Przetwórz wszystko": scan→group→resolve→calibrate→lineage→delta w jednym wątku. Anulowanie
        skanu PRZERYWA łańcuch (dalsze etapy się nie wykonują — baza spójna, re-skan dokończy).

        Kalibracja stoi PO resolverze, bo przepis flata bierze `frame.filter_canon`, a wypełnia go
        dopiero `run_resolver` (`resolver.py:137`) — odwrotna kolejność wyłoniłaby przepisy flatów
        z pustym filtrem, a następny przebieg przepiąłby te klatki do innego profilu. Rodowód stoi
        PO kalibracji, bo dopasowuje light do profili, które `calibrate` dopiero wyłania.

        Przejęcie zeznania (AR-5) stoi PO faktach kopii i PRZED `group`: predykat porównuje zeznanie
        klatki z faktami kopii, więc bez uzupełnienia nie ma czego porównać, a każdy etap od `group`
        w górę czyta `header` (oś teleskopu, `filter_canon`, przepis flata, rodowód). Przejęcie po nich
        zostawiłoby pochodne policzone z głosu nieobecnego pliku do NASTĘPNEJ dostawy."""
        if not self._scan(con):
            return
        if not self._copy_facts(con):
            return
        a = self._adopt_testimony(con)
        if a is not None and a.cancelled:
            return
        self._bulk(con, "group")
        self._bulk(con, "resolve")
        self._bulk(con, "calibrate")
        self._bulk(con, "lineage")
        self._bulk(con, "delta")
        # Obecność ZAWSZE w trybie DRY (raport dostawy ma być szczery: „nic nie znikło" to inna
        # wiadomość niż „nie sprawdziłem"). Zapis wymaga jawnego przycisku. Bez realnego serialu
        # pass nie ma kotwicy zakresu — pomijamy go zamiast straszyć abortem w złotej ścieżce.
        if self._params.get("volume", "?") != "?":
            self._presence(con, apply=False)
        else:
            # Cisza czytałaby się jak „sprawdzone, nic nie znikło" — a to jest „nie sprawdzone".
            self.stage_done.emit("presence", presence.PresenceSummary(
                aborted=i18n.t("pipeline.presence.skipped_no_volume")))

    def _copy_facts(self, con):
        """Uzupełnienie faktów KOPII z nagłówków (0021) - etap „Przyjmij nowe" zaraz po skanie.

        DLACZEGO TU, a nie osobny przycisk ani CLI: wydanie jedzie jako sam GUI (onefile - CLI
        nie powstaje), a kopie sprzed migracji skan z bramą przyrostową POMIJA (mtime bez zmian),
        więc bez tego etapu żywa baza nie dostałaby liczby obrazów ani zeznań kopii nigdy. Koszt
        jest jednorazowy: sterownik czyta SAME nagłówki (550 plików XISF archiwum ≈ 9 s po SMB
        zamiast 108,9 GB treści), a po pierwszym przebiegu jego SELECT jest pusty - wtedy etap
        milczy całkowicie (QUIET): ani „w toku", ani linii raportu, bo nie ma czego ogłaszać.

        ZAKRES = korzeń TEJ dostawy (jak pass obecności): „Przetwórz wszystko" na wskazanym
        katalogu nie czyta plików spoza niego. Anulowanie PRZERYWA łańcuch jak przy skanie - każda
        kopia to osobna transakcja, więc baza zostaje spójna, a następna dostawa dobierze resztę.
        Zwraca `False`, gdy anulowano."""
        root = self._params.get("root")
        if not scan.copy_facts_candidates(con, root):
            return True
        self.stage_started.emit("copy_facts")
        s = scan.backfill_copy_facts(con, now=self._now(), root=root,
                                     progress=self._on_copy_facts_progress,
                                     should_cancel=self._cancel.is_set)
        if s.cancelled:
            self.cancelled.emit("copy_facts", s)
            return False
        self.stage_done.emit("copy_facts", s)
        return True

    def _adopt_testimony(self, con):
        """Przejęcie zeznania ocalałej kopii (AR-5) - etap „Przyjmij nowe" zaraz po faktach kopii.

        Sterowany STANEM (`scan.adopt_candidates`): klatki, których `header` pochodzi z kopii już
        nieobecnej, a jedyna obecna kopia mówi co innego. Bez kandydatów etap milczy całkowicie
        (QUIET, wzorzec `_copy_facts`) - a milczy prawie zawsze, bo kandydatów jest tyle, ile
        skasowanych kopii. Klatki o dwóch i więcej obecnych kopiach albo z zeznaniem napisanym ręką
        etap zostawia człowiekowi (AR-4) - widać je w Porządkach („Zeznanie z nieobecnej kopii").

        ZAKRES = korzeń TEJ dostawy (jak `_copy_facts`). Anulowanie PRZERYWA łańcuch - każda klatka
        to osobna transakcja, więc baza zostaje spójna. Wołają go Dostawa (`_run_all`) i ogon gestu
        „Oznacz zniknięte" (`_after_vanished`). Zwraca `AdoptSummary` (wołający czyta `cancelled`
        i `adopted`) albo `None`, gdy kandydatów nie było."""
        root = self._params.get("root")
        if not scan.adopt_candidates(con, root):
            return None
        self.stage_started.emit("adopt_testimony")
        s = scan.adopt_orphan_testimony(con, now=self._now(), root=root,
                                        progress=self._on_adopt_progress,
                                        should_cancel=self._cancel.is_set)
        if s.cancelled:
            self.cancelled.emit("adopt_testimony", s)
        else:
            self.stage_done.emit("adopt_testimony", s)
        return s

    def _on_adopt_progress(self, done, total, path, s):
        if should_emit(done, total):
            self.progress.emit(done, total, path, {**counts_snapshot(s), "etap": "adopt_testimony"})

    def _on_copy_facts_progress(self, done, total, path, s):
        # Migawka jak przy skanie (dict przez granicę wątku, nigdy żywy obiekt); znacznik `etap`
        # mówi slotowi, której etykiety liczników użyć - liczniki skanu nie mają tu sensu.
        if should_emit(done, total):
            self.progress.emit(done, total, path, {**counts_snapshot(s), "etap": "copy_facts"})

    def _on_progress(self, done, total, path, summary):
        # wołane SYNCHRONICZNIE w wątku workera przez scan_tree; przerzedź i wyślij MIGAWKĘ (dict),
        # nigdy żywego ScanSummary (worker mutuje go dalej w pętli → race po stronie slotu).
        if should_emit(done, total):
            self.progress.emit(done, total, path, counts_snapshot(summary))


# Etykiety widoczne dla użytkownika = KLUCZE katalogu i18n (rozwiązywane `t()` w USE-site, po `set_lang`
# — nie module-level, D-L1 restart); wartości danych ("cold"/"scratch") to identyfikatory poziomu
# zapisywane do bazy (rdzeń `scan_tree`) — ZOSTAJĄ niezmienione. "—" neutralne — zostaje dosłowne.
_TIERS = [("—", None), ("pipeline.tier.cold", "cold"), ("pipeline.tier.scratch", "scratch")]
_STAGE_LABEL = {"scan": "pipeline.stage.scan", "stacks": "pipeline.stage.stacks",
                "group": "pipeline.stage.group",
                "resolve": "pipeline.stage.resolve", "calibrate": "pipeline.stage.calibrate",
                "lineage": "pipeline.stage.lineage", "delta": "pipeline.stage.delta",
                "presence": "pipeline.stage.presence",
                "stack_lineage": "pipeline.stage.stack_lineage",
                "copy_facts": "pipeline.stage.copy_facts",
                "adopt_testimony": "pipeline.stage.adopt_testimony"}

# Kolejność i klucze powodów przeglądu w raporcie dostawy (rdzeń niesie same liczby — wording należy
# do powierzchni; konsolowy `cli._format_delta` ma własne, ASCII-owe).
_REVIEW_REASONS = [("no_config", "pipeline.reason.no_config"),
                   ("headerless", "pipeline.reason.headerless"),
                   ("no_camera", "pipeline.reason.no_camera"),
                   ("kind_unknown", "pipeline.reason.kind_unknown"),
                   ("unreadable", "pipeline.reason.unreadable")]


def _stage_label(name):
    """Nazwa etapu w bieżącym języku (klucz z `_STAGE_LABEL`); nieznana → raw `name` (nie wołaj `t`
    na nie-kluczu)."""
    key = _STAGE_LABEL.get(name)
    return i18n.t(key) if key else name


def _review_line(st):
    """`ReviewState` → jedna linia raportu. Wiodąca liczba to DISTINCT klatek, po niej POWODY, które
    się nakładają (klatka bez kamery jest też bez konfiguracji) — dlatego „powody", nie „w tym":
    suma powodów bywa większa niż klatek i nie wolno jej czytać jak rozbicia. Zerowe powody milczą."""
    if not st.total:
        return i18n.t("pipeline.review.none")
    powody = ", ".join(f"{i18n.t(key)} {n}" for attr, key in _REVIEW_REASONS
                       if (n := getattr(st, attr)))
    return i18n.t("pipeline.review.line",
                  frames=i18n.t_plural("grid.frames", st.total), reasons=powody)


class PipelineView(QWidget):
    """Widok DOSTAWY (miejsce 1 nawigacji F5; historycznie „Pipeline", etap 2). Pionowy flow:
    baza → „Przyjmij nowe" (złota akcja: cała sekwencja na zapamiętanym źródle, D-UX-5) → tryb
    zaawansowany (katalog + tier + auto-wolumen, etapy pojedyncze) → skan z uczciwym % i anulowaniem
    → panel `ScanSummary` („co przyszło"). Stan widoczny BEZ klikania; UI nie kłamie (disabled gdy
    nie można). Serial wolumenu do bramy liczony ŚWIEŻO na starcie każdej sekwencji (`_scan_params`);
    skan `'?'` do bazy z realnymi wolumenami wstrzymuje guard `_serial_guard_ok` (F5R#3).

    Sygnały do gospodarza (`MainWindow`): `status_message(str)` (pasek statusu), `stage_finished(str)`
    (etap zakończył zapis — gospodarz odświeża read-model osi; WAL → widoczne), `running_changed(bool)`
    (etap w toku — gospodarz wyłącza akcje zapisu osi: szczery disabled, §6)."""

    status_message = Signal(str)
    stage_finished = Signal(str)
    running_changed = Signal(bool)
    open_collection = Signal(str)          # nazwa perspektywy Zbiorów (ścieżka 3→1 po oznaczeniu)

    def __init__(self, db_path, *, now_fn=_utc_now_iso, parent=None):
        super().__init__(parent)
        self._db_path = db_path
        self._now = now_fn
        self._root = None
        self._thread = None
        self._worker = None
        self._cancellable = False
        self._summary_lines = []
        self._presence_params = None       # ZAMROŻONE parametry ostatniego DRY (apply ich nie liczy)
        self._build_ui()
        self._sync_source_memo()
        self._sync_stacks_memo()
        self._sync_actions()

    # ---------------------------------------------------------------- budowa UI

    def _build_ui(self):
        v = QVBoxLayout(self)

        # 1. Baza (wskaźnik; Otwórz/Nowa są w menu Plik okna)
        self.lbl_db = QLabel()
        self.lbl_db.setText(i18n.t("main.db_loaded", path=self._db_path)
                            if self._db_path else i18n.t("pipeline.db_none"))
        v.addWidget(self.lbl_db)
        v.addWidget(self._hline())

        # 2. ZŁOTA akcja Dostawy (F5, D-UX-5): „Przyjmij nowe" = cała sekwencja na ZAPAMIĘTANYM
        # źródle (QSettings pipeline/last_source; pierwsza dostawa pyta o katalog). Waga wizualna
        # przejęta od dawnego „Przetwórz wszystko" (jedna złota akcja na miejsce, wzorzec F3 #3).
        rec = QHBoxLayout()
        self.btn_receive = QPushButton(i18n.t("pipeline.receive"))
        _f = self.btn_receive.font()
        _f.setBold(True)
        self.btn_receive.setFont(_f)
        self.btn_receive.setMinimumHeight(34)
        self.btn_receive.clicked.connect(self._on_receive)
        rec.addWidget(self.btn_receive, 1)
        v.addLayout(rec)
        self.lbl_source_memo = QLabel("")          # treść = WYŁĄCZNIE _sync_source_memo (F5R2#6)
        v.addWidget(self.lbl_source_memo)
        v.addWidget(self._hline())

        # 3. Tryb zaawansowany — źródło wskazywane ręcznie: katalog + poziom + auto-wolumen.
        # JAWNY nagłówek sekcji (wizytator F5 #4): bez niego dwie pełnoszerokie akcje konkurują.
        v.addWidget(QLabel(i18n.t("pipeline.advanced_head")))
        src = QHBoxLayout()
        self.btn_pick = QPushButton(i18n.t("pipeline.pick_dir"))
        self.btn_pick.clicked.connect(self._on_pick_dir)
        src.addWidget(self.btn_pick)
        self.lbl_root = QLabel(i18n.t("pipeline.root_none"))
        src.addWidget(self.lbl_root, 1)
        src.addWidget(QLabel(i18n.t("pipeline.tier_label")))
        self.combo_tier = QComboBox()
        for label, value in _TIERS:
            # "—" (value None) neutralne — nie klucz; reszta rozwiązuje etykietę z katalogu.
            self.combo_tier.addItem(i18n.t(label) if value is not None else label, value)
        src.addWidget(self.combo_tier)
        v.addLayout(src)
        self.lbl_volume = QLabel(i18n.t("pipeline.volume_none"))
        v.addWidget(self.lbl_volume)

        # „Przetwórz wszystko" na wskazanym katalogu — zwykły ciężar, BEZ dopisku sekwencji
        # (dublował złotą akcję — wizytator F5 #4; sekwencję nazywa „Przyjmij nowe" wyżej).
        self.btn_all = QPushButton(i18n.t("pipeline.process_all"))
        self.btn_all.clicked.connect(self._on_all)
        v.addWidget(self.btn_all)

        # 4. Etapy pojedyncze (tryb zaawansowany) + anulowanie (tylko skan/all jest przerywalny)
        stages = QHBoxLayout()
        self.btn_scan = QPushButton(i18n.t("pipeline.btn.scan"))
        self.btn_scan.clicked.connect(self._on_scan)
        self.btn_group = QPushButton(i18n.t("pipeline.btn.group"))
        self.btn_group.clicked.connect(self._on_group)
        self.btn_resolve = QPushButton(i18n.t("pipeline.btn.resolve"))
        self.btn_resolve.clicked.connect(self._on_resolve)
        self.btn_calibrate = QPushButton(i18n.t("pipeline.btn.calibrate"))
        self.btn_calibrate.setToolTip(i18n.t("pipeline.tip.calibrate"))
        self.btn_calibrate.clicked.connect(self._on_calibrate)
        self.btn_lineage = QPushButton(i18n.t("pipeline.btn.lineage"))
        self.btn_lineage.setToolTip(i18n.t("pipeline.tip.lineage"))
        self.btn_lineage.clicked.connect(self._on_lineage)
        self.btn_delta = QPushButton(i18n.t("pipeline.btn.delta"))
        self.btn_delta.clicked.connect(self._on_delta)
        self.btn_presence = QPushButton(i18n.t("pipeline.btn.presence"))
        self.btn_presence.setToolTip(i18n.t("pipeline.tip.presence"))
        self.btn_presence.clicked.connect(self._on_presence)
        self.btn_cancel = QPushButton(i18n.t("pipeline.btn.cancel"))
        self.btn_cancel.clicked.connect(self._on_cancel)
        for b in (self.btn_scan, self.btn_group, self.btn_resolve, self.btn_calibrate,
                  self.btn_lineage, self.btn_delta, self.btn_presence, self.btn_cancel):
            stages.addWidget(b)
        stages.addStretch(1)
        v.addLayout(stages)

        # 4a. Droga „Stosy" (I-2b, D-P-I-1 wariant A) — WŁASNA sekcja, nie ósmy przycisk etapu.
        # Rozdzielenie jest tu TREŚCIĄ, nie estetyką: wszystko powyżej dotyczy archiwum (`R:\ASTRO_`),
        # a ta akcja sięga do drzewa OBRÓBKI — innego korzenia, innego rytmu, innej odwracalności.
        # Wrzucenie jej między etapy sugerowałoby, że należy do sekwencji dostawy; nie należy.
        v.addWidget(self._hline())
        v.addWidget(QLabel(i18n.t("pipeline.stacks_head")))
        stk = QHBoxLayout()
        self.btn_stacks = QPushButton(i18n.t("pipeline.btn.stacks"))
        self.btn_stacks.setToolTip(i18n.t("pipeline.tip.stacks"))
        self.btn_stacks.clicked.connect(self._on_stacks)
        stk.addWidget(self.btn_stacks)
        # PRZELICZENIE BEZ WCIĄGANIA — osobny przycisk, bo to osobna potrzeba (firsthand 0808).
        # Rodowód stosów zależy od faktów, które człowiek nadaje MIĘDZY przebiegami (obiekt, zestaw,
        # odniesienie czasu), więc po każdym takim geście trzeba go policzyć od nowa. Dotąd jedyną
        # drogą było „Wciągnij stosy…" — czyli ponowny skan CAŁEGO drzewa obróbki plus pytanie
        # o korzeń, którego user już raz wskazał. Zdzin nazwał to wprost: „bez sensu dla usera,
        # skoro już wciągał raz". Etap istniał w workerze (`_bulk('stack_lineage')`) od I-2c
        # i był wołany wyłącznie z wnętrza drogi „Stosy”; tu dostaje własne wejście.
        self.btn_stack_lineage = QPushButton(i18n.t("pipeline.btn.stack_lineage"))
        self.btn_stack_lineage.setToolTip(i18n.t("pipeline.tip.stack_lineage"))
        self.btn_stack_lineage.clicked.connect(self._on_stack_lineage)
        stk.addWidget(self.btn_stack_lineage)
        self.lbl_stacks_memo = QLabel("")      # treść = WYŁĄCZNIE _sync_stacks_memo
        stk.addWidget(self.lbl_stacks_memo, 1)
        v.addLayout(stk)

        # 4b. Wynik passa obecności — UKRYTY, dopóki nie ma czego pokazać (QUIET: „0 zniknięć" to
        # linia w panelu, nie osobny widżet). Zapis jest ZAWSZE osobnym gestem: sekwencja tylko
        # RAPORTUJE, a przycisk pojawia się dopiero, gdy DRY coś potwierdził. Po oznaczeniu wchodzi
        # „Pokaż w Zbiorach" — ścieżka 3→1 wprost do perspektywy (wcześniej: raport → Porządki →
        # klik → Zbiory). „Pokaż" PRZED zapisem nie ma sensu: perspektywa czyta STAN present=0.
        self.box_vanished = QWidget()
        bv = QHBoxLayout(self.box_vanished)
        bv.setContentsMargins(0, 10, 0, 0)   # oddech: sekcja to WYNIK, nie siódmy przycisk etapu
        self.lbl_vanished = QLabel("")
        # BEZ zawijania: zdanie ma ~46 znaków (~300 px), a etykieta z `wordWrap` dostaje od Qt małą
        # preferowaną szerokość i łamie się na dwie linie mimo wolnego miejsca — wtedy przycisk stoi
        # przy PIERWSZEJ linii, a reszta zdania wisi pod nim. Cały wiersz (zdanie + 2 przyciski) mieści
        # się w ~600 px, więc nie podnosi podłogi szerokości okna (dziś **1310 px** — D-0801-1, wcześniej
        # 1073 zmierzone realnym fontem; zapis „1146" pochodził z sondy offscreen i był zawyżony).
        self.lbl_vanished.setWordWrap(False)
        _fv = self.lbl_vanished.font()
        _fv.setBold(True)                # to jedyny komunikat Dostawy o UTRACIE — nie może ważyć
        self.lbl_vanished.setFont(_fv)   # tyle, co wiersz „wolumen: …" (wizytator P5 #6)
        # Etykieta i JEJ przyciski trzymają się razem, stretch idzie NA KONIEC. Z `addWidget(lbl, 1)`
        # przycisk odlatywał na prawą krawędź okna — przy 1200 px to ~1150 px pustki między zdaniem
        # a akcją, którą to zdanie zapowiada (ten sam defekt, co w liście zadań: wizytator P1 #2).
        bv.addWidget(self.lbl_vanished)
        self.btn_mark_vanished = QPushButton(i18n.t("pipeline.btn.mark_vanished"))
        self.btn_mark_vanished.clicked.connect(self._on_mark_vanished)
        bv.addWidget(self.btn_mark_vanished)
        self.btn_show_vanished = QPushButton(i18n.t("pipeline.btn.show_collections"))
        self.btn_show_vanished.clicked.connect(lambda: self.open_collection.emit(PRESET_VANISHED))
        self.btn_show_vanished.setVisible(False)
        bv.addWidget(self.btn_show_vanished)
        bv.addStretch(1)
        self.box_vanished.setVisible(False)
        v.addWidget(self.box_vanished)

        # 5. Pasek + liczniki (wspólne: skan = uczciwy %; etapy masowe = busy spinner). Pasek UKRYTY
        # w spoczynku — wizytator P2: „0%" w idle kłamie, że coś ruszyło. Pojawia się w _begin_run.
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setVisible(False)
        v.addWidget(self.bar)
        self.lbl_counts = QLabel("")
        v.addWidget(self.lbl_counts)

        # 6. Błąd etapu — OSOBNY wiersz, kolor semantyczny (wizytator P2: błąd nie może ginąć wśród
        # czarnych wierszy panelu). Ukryty dopóki nie padnie failed.
        # Kolor Z MOTYWU (`role="error"` → `theme.qss`), nie inline: sztywne `#b00020` przeżyło F6
        # i na ciemnej bazie #2B2B2B dawało 1,6:1 — jedyny sygnał porażki etapu był nieczytelny
        # dokładnie w motywie DOMYŚLNYM (P-C).
        self.lbl_error = QLabel("")
        self.lbl_error.setProperty("role", "error")
        self.lbl_error.setWordWrap(True)
        self.lbl_error.setVisible(False)
        v.addWidget(self.lbl_error)

        # 7. Panel podsumowania — akumuluje wiersz per (pod)etap (handoff delty do import-legacy)
        self.lbl_summary = QLabel("")
        self.lbl_summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lbl_summary.setWordWrap(True)
        v.addWidget(self.lbl_summary)
        v.addStretch(1)

    def _forget_vanished(self):
        """Schowaj sekcję i zapomnij ZAMROŻONE parametry — po tym „Oznacz zniknięte" nie ma czego
        zapisać (guard w `_on_mark_vanished`), więc nie da się utrwalić wyniku, którego user już
        nie widzi na ekranie."""
        self._presence_params = None
        self.box_vanished.setVisible(False)
        self._sync_actions()

    def _hline(self):
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        return line

    # ---------------------------------------------------------------- źródło

    def _settings(self):
        return QSettings("Horreum", "Horreum")

    def _sync_source_memo(self):
        """JEDYNY właściciel treści memo źródła (F5R2#6) — wołane z __init__ i po KAŻDYM zapisie
        `pipeline/last_source` (stare memo po zmianie źródła kłamałoby)."""
        source = self._settings().value("pipeline/last_source", None)
        if source:
            self.lbl_source_memo.setText(i18n.t("pipeline.source_last", source=source))
        else:
            self.lbl_source_memo.setText(i18n.t("pipeline.source_first"))

    def _remember_source(self, path):
        self._settings().setValue("pipeline/last_source", path)
        self._sync_source_memo()

    def _set_root(self, path):
        """Ustaw źródło skanu + etykiety. Serial na etykiecie jest INFORMACYJNY (stan z tej chwili);
        wartość do bramy `(volume,path,mtime)` liczy ZAWSZE `_scan_params` na starcie sekwencji
        (R#7+R2-3 — serial z pamięci/montażu bywa stale po przepięciu dysku w trakcie sesji)."""
        self._root = path
        self.lbl_root.setText(path)
        self._forget_vanished()      # wynik passa dotyczy STAREGO drzewa — po zmianie źródła kłamie
        serial = volume_serial(path)
        if serial is None:
            # Neutralnie — skutek ('?' = pełny skan ALBO stop przy mieszanej bazie) nazywa wyłącznie
            # guard na starcie sekwencji; obietnica tutaj przeczyłaby mu (wizytator F5 #5).
            self.lbl_volume.setText(i18n.t("pipeline.volume_unset"))
        else:
            self.lbl_volume.setText(i18n.t("pipeline.volume_ok", serial=serial))
        self._sync_actions()

    def _on_pick_dir(self):
        path = QFileDialog.getExistingDirectory(self, i18n.t("pipeline.dlg.pick_scan"))
        if not path:
            return
        self._remember_source(path)     # D-UX-5: jedna pamięć ostatniego katalogu (pick i receive)
        self._set_root(path)

    # ---------------------------------------------------------------- korzeń stosów (I-2b)

    def _sync_stacks_memo(self):
        """JEDYNY właściciel treści memo korzenia stosów (wzorzec `_sync_source_memo`) — wołane
        z `__init__` i po KAŻDYM zapisie `stacks/last_root`."""
        root = self._settings().value("stacks/last_root", None)
        self.lbl_stacks_memo.setText(i18n.t("pipeline.stacks_last", root=root) if root
                                     else i18n.t("pipeline.stacks_first"))

    def _on_stack_lineage(self):
        """Przelicz rodowód gotowych stosów — BEZ skanu i BEZ pytania o korzeń.

        Dlaczego to nie jest ten sam gest, co „Wciągnij stosy…": tamten pyta o katalog, bo wciąga
        z DYSKU nowe pliki, a drzewo obróbki żyje. Ten liczy wyłącznie z tego, co JUŻ jest w bazie
        — a to zmienia się gestami człowieka (obiekt, zestaw, odniesienie czasu), nie zawartością
        dysku. Ta sama droga rdzenia (`_bulk('stack_lineage')`), inne wejście i inna cena.

        IDEMPOTENTNY: drugi przebieg na niezmienionych danych daje zero wierszy i jedno zdarzenie
        zbiorcze (kanon `run_stack_lineage`; E2-1 pilnuje, żeby docstring tego nie zawyżał)."""
        if self._db_path is None or self._thread is not None:
            return
        self._begin_run()
        self._start_stage("stack_lineage")

    def _on_stacks(self):
        """Droga „Stosy" — ZAWSZE przez dialog katalogu, ale PODPOWIEDZIANY zapamiętanym korzeniem
        (`stacks/last_root`, QSettings per maszyna; ścieżka na dysku jest własnością BIURKA, nie
        archiwum, więc do bazy nie idzie mimo D-P-I-3).

        Dlaczego pytamy za każdym razem, choć „Przyjmij nowe" nie pyta: tam korzeniem jest ustalone
        archiwum, tu — drzewo obróbki, które ŻYJE (foldery wędrują między dyskami i rocznikami).
        Milczące wciągnięcie starego korzenia byłoby zapisem do bazy na podstawie pamięci sprzed
        miesięcy. Podpowiedź daje jedno kliknięcie różnicy i zero zgadywania."""
        if self._db_path is None or self._thread is not None:
            return
        last = str(self._settings().value("stacks/last_root", "") or "")
        root = QFileDialog.getExistingDirectory(self, i18n.t("pipeline.dlg.pick_stacks"), last)
        if not root:
            return
        self._settings().setValue("stacks/last_root", root)
        self._sync_stacks_memo()
        # Serial ŚWIEŻO dla TEGO korzenia (nie z `_scan_params` — tamten mierzy korzeń archiwum).
        # Guard mieszania serialu obowiązuje tak samo: '?' do bazy ze znanymi wolumenami podwoiłby
        # lokacje przy drugim przebiegu i zabrałby drodze idempotencję.
        serial = volume_serial(root)
        params = dict(root=root, volume=serial if serial is not None else "?",
                      drive_letter=(Path(root).drive or None), tier=self.combo_tier.currentData())
        if not self._serial_guard_ok(params):
            return
        self._begin_run()
        self._start_stage("stacks", **params)

    # ---------------------------------------------------------------- akcje (worker)

    def _scan_params(self):
        # Serial ŚWIEŻO na starcie KAŻDEJ sekwencji (all/scan/receive) — nigdy z pamięci ani
        # z montażu (R#7+R2-3); nieustalony → '?' → pełny skan (kontrakt bramy).
        serial = volume_serial(self._root)
        return dict(
            root=self._root,
            volume=serial if serial is not None else "?",
            drive_letter=(Path(self._root).drive or None),
            tier=self.combo_tier.currentData(),
        )

    def _serial_guard_ok(self, params):
        """Guard mieszania serialu (F5R#3): skan `'?'` do bazy znającej REALNE wolumeny PODWOIŁBY
        lokacje każdej znanej klatki (brama `(volume,path,mtime)` nie trafi, `UNIQUE(volume,path)`
        wpuści drugą) → zadanie „Duplikaty" i perspektywa kłamią na masę. Warunek = konserwatywny
        NADZBIÓR podwojenia (bez bypassa w v1 — decyzja jawna F5R2#3); czysty świat `'?'`
        (nie-Windows) przechodzi. Krótkie WŁASNE połączenie (F5R2#4: baza już zmigrowana →
        `db.connect`; finally zamyka — wiszący czytelnik WAL)."""
        if params["volume"] != "?":
            return True
        con = db.connect(self._db_path)
        try:
            mixed = queries.has_real_volume_locations(con)
        finally:
            con.close()
        if not mixed:
            return True
        msg = i18n.t("pipeline.guard.mixed")
        self.lbl_error.setText(i18n.t("pipeline.error_prefix", msg=msg))
        self.lbl_error.setVisible(True)
        self.status_message.emit(msg)       # konwencja _on_failed: lbl_error + status (F5R2#5)
        return False

    def _start_scan_sequence(self, stage):
        """Wspólna sekwencja startu skanujących ścieżek (F5R2#2 — JEDEN pomiar serialu, JEDEN dom
        guardu): params → guard → begin → start."""
        params = self._scan_params()
        if not self._serial_guard_ok(params):
            return
        self._begin_run()
        self._start_stage(stage, **params)

    def _on_receive(self):
        """„Przyjmij nowe" (F5, D-UX-5): cała sekwencja na ZAPAMIĘTANYM źródle; brak pamięci albo
        katalog zniknął (plik-nie-katalog wpada w ten sam warunek) → pytanie o katalog + zapis."""
        if self._db_path is None or self._thread is not None:
            return
        source = self._settings().value("pipeline/last_source", None)
        if not source or not Path(source).is_dir():
            source = QFileDialog.getExistingDirectory(self, i18n.t("pipeline.dlg.pick_delivery"))
            if not source:
                return
        self._remember_source(source)
        self._set_root(source)
        self._start_scan_sequence("all")

    def _begin_run(self):
        """Wyzeruj panel/pasek przed nowym przebiegiem (summary akumuluje per etap, więc czyścimy).
        Sekcja zniknięć gaśnie RAZEM z panelem: zdanie „Zniknęły 2 kopie" bez raportu, do którego
        się odnosi, wisiałoby nad wynikiem zupełnie innego etapu (wizytator P5 #9)."""
        self._summary_lines = []
        self._forget_vanished()
        self.lbl_summary.setText("")
        self.lbl_error.setVisible(False)
        self.lbl_error.setText("")
        self.bar.setVisible(True)
        self.bar.setRange(0, 0)
        self.lbl_counts.setText("")

    def _on_all(self):
        if not self._can_scan() or self._thread is not None:
            return
        self._start_scan_sequence("all")

    def _on_scan(self):
        if not self._can_scan() or self._thread is not None:
            return
        self._start_scan_sequence("scan")

    def run_stage(self, stage):
        """PUBLICZNE wejście w etap masowy (group/resolve/calibrate/lineage/delta) — jedyna droga dla
        powierzchni SPOZA tego widoku (P-D/D-PD-6: dialog „Napraw nagłówek…" po zapisie kart woła
        `run_stage('resolve')`). Zwraca **POWÓD ODMOWY** (string) albo `None`, gdy etap wystartował.

        Powód, nie `bool`: jedna bramka łączy dwa różne stany („nie ma bazy" i „etap już biegnie"),
        więc komunikat oparty na gołym False mógłby skłamać, a guard jest tu HISTORYCZNIE CICHY
        (sloty po prostu wracały). Wołanie rdzenia inline byłoby błędem: `run_resolver` off-thread
        żyje wyłącznie w `PipelineWorker`, więc bezpośrednie wywołanie zamroziłoby GUI na 15k klatek
        I ominęło `running_changed` → gospodarz zostawiłby aktywne akcje zapisu w gridzie, na osi
        i w planerze podczas biegu w tle.

        Pięć slotów masowych deleguje TU (jeden dom bramki zamiast pięciu kopii). Poza fasadą
        świadomie: `_on_scan`/`_on_all` (własny `_can_scan()` + bramka serialu wolumenu),
        `_on_presence`/`_on_mark_vanished` (własne parametry) — wciągnięcie ich zgubiłoby te
        bramki albo uczyniło fasadę niejednolitą."""
        if self._db_path is None:
            return i18n.t("pipeline.refuse.no_db")
        if self._thread is not None:
            return i18n.t("pipeline.refuse.running")
        self._begin_run()
        self._start_stage(stage)
        return None

    def _on_group(self):
        self.run_stage("group")

    def _on_resolve(self):
        self.run_stage("resolve")

    def _on_calibrate(self):
        self.run_stage("calibrate")

    def _on_lineage(self):
        self.run_stage("lineage")

    def _on_delta(self):
        self.run_stage("delta")

    def _on_presence(self):
        """Etap pojedynczy — ZAWSZE DRY. Zapis idzie wyłącznie przez „Oznacz zniknięte"."""
        if not self._can_scan() or self._thread is not None:
            return
        self._begin_run()
        self._start_stage("presence", **self._scan_params())

    def _on_mark_vanished(self):
        """Jawny gest zapisu na WYNIKU, który user właśnie zobaczył: parametry ZAMROŻONE przy DRY,
        żeby przycisk nie znaczył czegoś innego niż raport nad nim (wzorzec „Wydaj na stół")."""
        if self._thread is not None or self._presence_params is None:
            return
        params = self._presence_params            # zdejmij PRZED _begin_run (ono je zapomina)
        self._begin_run()
        self._start_stage("presence-apply", **params)

    def _on_cancel(self):
        if self._worker is not None:
            self._worker.request_cancel()
            self.status_message.emit(i18n.t("pipeline.cancelling"))

    def _start_stage(self, stage, **params):
        self._worker = PipelineWorker(self._db_path, now_fn=self._now)
        self._worker.configure(stage, **params)
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.stage_started.connect(self._on_stage_started)
        self._worker.stage_done.connect(self._on_stage_done)
        self._worker.cancelled.connect(self._on_cancelled)
        self._worker.failed.connect(self._on_failed)
        # quit DOPIERO gdy run() w całości wróci (`finished`) — przy „all" leci wiele stage_done,
        # więc NIE wolno kończyć wątku na pierwszym z nich.
        self._worker.finished.connect(self._thread.quit)
        self._thread.finished.connect(self._cleanup_thread)
        self._set_running(True, cancellable=stage in ("scan", "stacks", "all",
                                                      "presence", "presence-apply"))
        self._thread.start()

    def _cleanup_thread(self):
        # wait() PRZED thread.deleteLater() — deadlock GIL × ~QThread jak w
        # projection_dialog._cleanup_dry_thread (komentarz tam); wait() zwalnia GIL,
        # więc teardown wątku dokończy destrukcję workera (PyGILState_Ensure) i umrze.
        self._worker.deleteLater()
        self._thread.wait()
        self._thread.deleteLater()
        self._worker = None
        self._thread = None
        self._set_running(False)

    # ---------------------------------------------------------------- sloty (główny wątek)

    @Slot(int, int, str, dict)
    def _on_progress(self, done, total, path, counts):
        if self.bar.maximum() != total:
            self.bar.setRange(0, total)
        self.bar.setValue(done)
        tail = path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
        if counts.get("etap") == "copy_facts":        # uzupełnienie faktów kopii (0021)
            self.lbl_counts.setText(i18n.t("pipeline.counts_copy_facts", done=done, total=total,
                                           written=counts["written"], tail=tail))
            return
        if counts.get("etap") == "adopt_testimony":   # przejęcie zeznania (AR-5)
            self.lbl_counts.setText(i18n.t("pipeline.counts_adopt", done=done, total=total,
                                           adopted=counts["adopted"], tail=tail))
            return
        do_przegladu = counts["frame_review"] + counts["camera_review"]
        self.lbl_counts.setText(i18n.t(
            "pipeline.counts", done=done, total=total, new=counts["frames_new"],
            skipped=counts["skipped"], review=do_przegladu, tail=tail))

    @Slot(str)
    def _on_stage_started(self, name):
        # skan: pasek nieokreślony do 1. progresu; etap masowy: busy spinner (bez progresu per-wiersz)
        self.bar.setRange(0, 0)
        self.lbl_counts.setText(i18n.t("pipeline.stage_running", stage=_stage_label(name)))

    @Slot(str, object)
    def _on_stage_done(self, name, result):
        self.bar.setRange(0, 1)
        self.bar.setValue(1)
        self.lbl_counts.setText("")
        self._append_summary(self._format_result(name, result))
        if name == "presence":
            self._update_vanished_box(result)
        self.status_message.emit(i18n.t("pipeline.stage_done_status", stage=_stage_label(name)))
        self.stage_finished.emit(name)                  # gospodarz odświeża oś (WAL)

    @Slot(str, object)
    def _on_cancelled(self, name, summary):
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        self.lbl_counts.setText("")
        # Anulować da się KAŻDY przerywalny etap, nie tylko skan (P5: pass obecności też) — twarde
        # `[skan]` + `summary.files` wywalało slot AttributeError na `PresenceSummary`, a wtedy panel
        # zostawał pusty, pasek na 0% i status „Anulowanie…" na wieki (wizytator P5 #1).
        etykieta = _stage_label(name)
        if name == "scan":
            self._append_summary(i18n.t("pipeline.scan_cancelled", n=summary.files))
        self._append_summary(self._format_result(name, summary))
        self.status_message.emit(i18n.t("pipeline.stage_interrupted", stage=etykieta))
        self.stage_finished.emit(name)                  # częściowy zapis też trzeba odświeżyć

    @Slot(str, str)
    def _on_failed(self, name, msg):
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        self.lbl_counts.setText("")
        self.lbl_error.setText(i18n.t("pipeline.stage_failed_line", stage=_stage_label(name), msg=msg))
        self.lbl_error.setVisible(True)                 # czerwony, osobny wiersz — nie ginie w panelu
        self.status_message.emit(i18n.t("pipeline.stage_failed_status", stage=name))

    # ---------------------------------------------------------------- formatowanie / stan przycisków

    def _append_summary(self, line):
        self._summary_lines.append(line)
        self.lbl_summary.setText("\n".join(self._summary_lines))

    def _format_result(self, name, r):
        if name == "scan":
            return self._format_scan(r)
        if name == "group":
            return self._format_group(r)
        if name == "resolve":
            return self._format_resolve(r)
        if name == "calibrate":
            return self._format_calibrate(r)
        if name == "lineage":
            return self._format_lineage(r)
        if name == "delta":
            return self._format_delta(r)
        if name == "presence":
            return self._format_presence(r)
        if name == "stacks":
            return self._format_stacks(r)
        if name == "stack_lineage":
            return self._format_stack_lineage(r)
        if name == "copy_facts":
            return self._format_copy_facts(r)
        if name == "adopt_testimony":
            return self._format_adopt(r)
        return str(r)

    def _format_adopt(self, s):
        """Linia raportu przejęcia zeznania (AR-5). Odmowy tylko, gdy są (QUIET), każda z przyczyną;
        `czeka` mówi, ile klatek dalej mówi głosem nieobecnej kopii po tym przebiegu."""
        czesci = [i18n.t("pipeline.fmt.adopt.adopted", n=s.adopted, rows=s.rows)]
        if s.identity:
            czesci.append(i18n.t("pipeline.fmt.adopt.identity", n=s.identity))
        if s.stale:
            czesci.append(i18n.t("pipeline.fmt.adopt.stale", n=s.stale))
        if s.raced:
            czesci.append(i18n.t("pipeline.fmt.adopt.raced", n=s.raced))
        if s.failed:
            czesci.append(i18n.t("pipeline.fmt.adopt.failed", n=s.failed))
        if s.remaining:
            czesci.append(i18n.t("pipeline.fmt.adopt.remaining", n=s.remaining))
        return i18n.t("pipeline.fmt.adopt.prefix") + " · ".join(czesci)

    def _format_copy_facts(self, s):
        """Linia raportu uzupełnienia faktów kopii (0021). Odmowy tylko, gdy są (QUIET), ale gdy są,
        stoją obok liczby uzupełnionych, a `czeka` mówi, ile zostało na następną dostawę - „uzupełniono
        540 z 550" bez przyczyny reszty byłoby raportem, który zataja, dlaczego reszta czeka."""
        czesci = [i18n.t("pipeline.fmt.copy_facts.written", n=s.written, rows=s.rows)]
        if s.stale:
            czesci.append(i18n.t("pipeline.fmt.copy_facts.stale", n=s.stale))
        if s.failed:
            czesci.append(i18n.t("pipeline.fmt.copy_facts.failed", n=s.failed))
        if s.remaining:
            czesci.append(i18n.t("pipeline.fmt.copy_facts.remaining", n=s.remaining))
        return i18n.t("pipeline.fmt.copy_facts.prefix") + " · ".join(czesci)

    def _format_stack_lineage(self, s):
        """Linia raportu rodowodu stosów (I-2d). Mówi TRZY rzeczy naraz i żadnej nie da się pominąć:
        ile obrazów wie, z czego powstało; ile z tego jest DOWIEDZIONE zeznaniem pliku (reszta to
        kandydaci z okna czasu); ile czeka na rękę i dlaczego. Sam „rodowód: 81" byłby liczbą
        udającą pewność."""
        czesci = [i18n.t("pipeline.fmt.slin.linked", n=s.linked, total=s.stacks, inputs=s.inputs)]
        if s.by_assert.get("history"):
            czesci.append(i18n.t("pipeline.fmt.slin.history", n=s.by_assert["history"]))
        czekaja = sum(s.reasons.values())
        if czekaja:
            czesci.append(i18n.t("pipeline.fmt.slin.waiting", n=czekaja))
        if s.ambiguous:
            czesci.append(i18n.t("pipeline.fmt.slin.ambiguous", n=s.ambiguous))
        if s.telescope_mismatch:
            czesci.append(i18n.t("pipeline.fmt.slin.telescope", n=s.telescope_mismatch))
        # PRZEBIEG, KTÓRY ŚWIADOMIE NIC NIE ZAPISAŁ, NIE MA PRAWA WYGLĄDAĆ JAK UDANY. Strażnik 4
        # zostawia gotowy rodowód nietknięty, gdy pliku nie ma pod ręką (odłączone archiwum) —
        # bez tego członu okno pokazywało te same liczby co po realnym przeliczeniu, a jedyna
        # wzmianka szła do CLI, którego wydanie w ogóle nie ma (onefile jest sam GUI).
        # ROZBICIE, nie próg: przy mieszance przyczyn żaden pojedynczy komunikat nie jest
        # prawdziwy dla obu połówek, a recepta jest tu ważniejsza niż liczba.
        if s.kept_unread - s.kept_no_location:
            czesci.append(i18n.t("pipeline.fmt.slin.kept_unread",
                                 n=s.kept_unread - s.kept_no_location))
        if s.kept_no_location:
            czesci.append(i18n.t("pipeline.fmt.slin.kept_no_location", n=s.kept_no_location))
        # TRZECI powód pominięcia (S2b), jedyny BEZ recepty: zapisany dowód jest mocniejszy od
        # tego, co przebieg umiał policzyć. Bez tego członu gest osi obiektu na lighcie dowiedzionego
        # stosu dawałby przebieg o zerowej delcie i milczącym oknie — nieodróżnialny od bezczynności.
        if s.kept_proven:
            czesci.append(i18n.t("pipeline.fmt.slin.kept_proven", n=s.kept_proven))
        return i18n.t("pipeline.fmt.slin.prefix") + " · ".join(czesci)

    def _format_stacks(self, s):
        """Linia raportu drogi „Stosy". ODMOWY mają własne człony i pojawiają się TYLKO, gdy są
        (QUIET) — ale gdy są, muszą stać obok liczby wciągniętych: „wciągnięto 128" bez „odrzucono
        3" byłoby raportem, który zataja, że coś zostało za drzwiami. Pochodne obróbki liczymy
        zawsze, bo to nie odmowa, tylko granica zakresu (§5 briefu P-I)."""
        czesci = [i18n.t("pipeline.fmt.stacks.taken", n=s.ingested, cand=s.candidates),
                  i18n.t("pipeline.fmt.stacks.derived", n=s.derived_skipped)]
        if s.skipped:
            czesci.append(i18n.t("pipeline.fmt.stacks.skipped", n=s.skipped))
        if s.rejected_kind:
            czesci.append(i18n.t("pipeline.fmt.stacks.rejected_kind", n=s.rejected_kind))
        if s.rejected_unreadable:
            czesci.append(i18n.t("pipeline.fmt.stacks.rejected_unreadable", n=s.rejected_unreadable))
        if s.failed:
            czesci.append(i18n.t("pipeline.fmt.stacks.failed", n=s.failed))
        # PRZEBIEG NIEKOMPLETNY musi dojść TU, nie tylko do CLI (bramka pakietu 3a, zarzut 2):
        # GUI jest jedyną powierzchnią użytkową, więc naprawa „zerwany share ≠ pusto" żyjąca
        # wyłącznie w konsoli nie naprawia niczego dla człowieka, który patrzy na ekran.
        if s.unreadable_dirs:
            czesci.append(i18n.t("pipeline.fmt.stacks.unreadable", n=len(s.unreadable_dirs)))
        return i18n.t("pipeline.fmt.stacks.prefix") + " · ".join(czesci)

    def _format_presence(self, s):
        """Linia raportu passa obecności. Zero zniknięć MUSI być zdaniem („nic nie znikło"), nie
        ciszą: cisza w raporcie dostawy czyta się jak „nie sprawdzono". Kubełki, które NIE są
        zniknięciami, pokazujemy tylko gdy niezerowe."""
        if s.aborted is not None:
            return i18n.t("pipeline.fmt.presence.not_done", reason=s.aborted)
        if s.cancelled:
            return i18n.t("pipeline.fmt.presence.cancelled")
        czesci = [i18n.t("pipeline.fmt.presence.scope", scoped=s.scoped, walked=s.walked)]
        if s.out_of_reach:
            czesci.append(i18n.t("pipeline.fmt.presence.out_of_reach", n=s.out_of_reach))
        if s.run_id is not None:
            czesci.append(i18n.t("pipeline.fmt.presence.marked", n=s.vanished))
        else:
            czesci.append(i18n.t("pipeline.fmt.presence.gone", n=s.confirmed_gone)
                          if s.confirmed_gone else i18n.t("pipeline.fmt.presence.nothing_gone"))
        if s.resurfaced:
            czesci.append(i18n.t("pipeline.fmt.presence.resurfaced", n=s.resurfaced))
        if s.undecided:
            czesci.append(i18n.t("pipeline.fmt.presence.undecided", n=s.undecided))
        if s.drifted:
            czesci.append(i18n.t("pipeline.fmt.presence.drifted", n=s.drifted))
        line = i18n.t("pipeline.fmt.presence.prefix") + " · ".join(czesci)
        return line + f" · {s.brake}" if s.brake else line

    def _update_vanished_box(self, s):
        """Sekcja 4b: co user może ZROBIĆ z wynikiem. Rozróżnienie DRY↔zapis po `run_id` (ustawia go
        wyłącznie faza zapisu) — po oznaczeniu przycisk zapisu znika, bo nie ma już czego oznaczać,
        a wchodzi droga do perspektywy."""
        applied = s.run_id is not None
        if applied:
            self._presence_params = None
            kopie = i18n.t_plural("pipeline.marked_copies", s.vanished)
            # Druga liczba jest KONIECZNA: zniknięcie jednej z dwóch kopii nie odbiera klatce
            # obecności, więc „oznaczono 3 kopie" potrafi dać PUSTĄ listę zniknięć (wiz P5 #3).
            klatki = i18n.t_plural("pipeline.frames_lost_last", s.frames_without_copy)
            ogon = klatki if s.frames_without_copy else i18n.t("pipeline.no_frame_lost_last")
            self.lbl_vanished.setText(i18n.t("pipeline.marked_as_vanished", copies=kopie, tail=ogon))
            self.btn_mark_vanished.setVisible(False)
            self.btn_show_vanished.setVisible(bool(s.frames_without_copy))   # lista MUSI mieć treść
            self.box_vanished.setVisible(bool(s.vanished))
        elif s.confirmed_gone and s.aborted is None and not s.cancelled:
            self._presence_params = dict(root=self._root, volume=s.volume)   # ZAMROŻONE
            n = s.confirmed_gone
            self.lbl_vanished.setText(i18n.t_plural("pipeline.vanished_still_present", n))
            self.btn_mark_vanished.setVisible(True)
            self.btn_show_vanished.setVisible(False)
            self.box_vanished.setVisible(True)
        else:
            self._presence_params = None
            self.box_vanished.setVisible(False)
        self._sync_actions()

    def _format_scan(self, s):
        linia = i18n.t(
            "pipeline.fmt.scan", files=s.files, new=s.frames_new, existing=s.frames_existing,
            skipped=s.skipped, excluded=s.dirs_excluded, loc_new=s.locations_new,
            loc_ref=s.locations_refreshed, hdr_ref=s.headers_refreshed, rebound=s.locations_rebound,
            headers=s.headers, frame_review=s.frame_review, camera_review=s.camera_review,
            kind=s.kind_unmapped)
        # Odsiew pochodnych pod `STACKS` — człon warunkowy (QUIET: zero pochodnych to cisza), ale
        # gdy jest, MUSI być widoczny (bramka pakietu 3a, zarzut 3). Komentarz przy polu obiecuje
        # „wykluczenie WIDOCZNE, nie cichy licznik", a jedyna powierzchnia użytkowa go nie pokazywała.
        if s.derived_skipped:
            linia += " · " + i18n.t("pipeline.fmt.scan_derived", n=s.derived_skipped)
        # PRZEBIEG NIEKOMPLETNY (E4-6) — ten sam człon, który dostała droga „Stosy", tyle że tu
        # broni drogi GŁÓWNEJ. Bez niego zerwany share w połowie archiwum daje linię raportu nie
        # do odróżnienia od zdrowego doskanu, w którym nic nie przybyło: same niższe liczby.
        if s.unreadable_dirs:
            linia += " · " + i18n.t("pipeline.fmt.scan_unreadable", n=len(s.unreadable_dirs))
        return linia

    def _format_group(self, s):
        unassigned = (i18n.t("pipeline.fmt.group_unassigned", n=s.configs_unassigned)
                      if s.configs_unassigned else "")
        # R1b: klatki z zestawem od RĘKI przebieg mija — i raport musi to powiedzieć, inaczej po
        # geście widać sam SPADEK dwóch liczników bez przyczyny („przebieg naprawił coś sam").
        by_hand = (i18n.t("pipeline.fmt.group_by_hand", n=s.config_by_hand)
                   if s.config_by_hand else "")
        return i18n.t(
            "pipeline.fmt.group", headers=s.headers, telescopes=s.telescopes_proposed,
            no_tel=s.telescop_missing, off_axis=s.calibration_off_axis, unassigned=unassigned,
            by_hand=by_hand,
            conf_prop=s.configs_proposed, conf_assign=s.configs_assigned, conf_review=s.config_review)

    def _format_resolve(self, s):
        """Linia raportu osi obiektu. Ruch SŁOWNIKA obiektów własnych dopisujemy tylko wtedy, gdy
        zaszedł (QUIET) — ale gdy zaszedł, MUSI być widoczny: edycja assetu odpina klatki, a
        kolizja nazwy jest jedyną rzeczą w tym przebiegu, którą rozstrzyga człowiek. Bez tej
        doklejki cztery liczniki `ResolveSummary` nie miały powierzchni w aplikacji okienkowej."""
        linia = i18n.t(
            "pipeline.fmt.resolve", frames=s.frames, lights=s.light_frames, obj_new=s.objects_new,
            obj_assign=s.objects_assigned, obj_review=s.objects_review,
            obj_distinct=s.objects_unresolved_distinct, filters=s.filters_set)
        if s.own_aliases_seeded or s.own_aliases_retired or s.own_frames_unassigned:
            linia += i18n.t("pipeline.fmt.resolve_own", seeded=s.own_aliases_seeded,
                            retired=s.own_aliases_retired, unassigned=s.own_frames_unassigned)
        if s.own_alias_conflicts:
            linia += i18n.t("pipeline.fmt.resolve_own_conflict", n=s.own_alias_conflicts)
        # SZCZEBEL ŚCIEŻKI (S2, D-OW-2/B) — przebieg go LICZY i nic nie zapisuje, więc bez tej
        # doklejki Dostawa milczałaby o klatkach czekających na gest człowieka, a jedynym śladem
        # byłby wiersz w kolejce INNEGO widoku. Zero propozycji = cisza (QUIET).
        if s.path_proposed_frames:
            linia += i18n.t("pipeline.fmt.resolve_path", names=s.path_proposed_names,
                            frames=s.path_proposed_frames)
        # E5-1: nagłówek przegłosował potwierdzenie ze ścieżki. Inny obiekt = gest człowieka
        # przegrał z plikiem (ostrzeżenie); ten sam = zmieniło się tylko źródło. Zero = cisza.
        if s.objects_path_overridden:
            linia += i18n.t_plural("pipeline.fmt.resolve_path_overridden",
                                   s.objects_path_overridden)
        if s.objects_path_to_header:
            linia += i18n.t_plural("pipeline.fmt.resolve_path_to_header",
                                   s.objects_path_to_header)
        return linia

    def _format_calibrate(self, s):
        """Linia raportu osi przepisu. Powody braku kompletu WYPISUJEMY (nie tylko liczbę): „bez
        kompletu 6" nie mówi, czego dopisać ręką w C3, a to jest jedyna akcja, jaką user ma tu do
        wykonania. Zerowe braki milczą (QUIET)."""
        linia = i18n.t(
            "pipeline.fmt.calibrate", frames=s.frames, prof_prop=s.profiles_proposed,
            prof_assign=s.profiles_assigned, facts=s.facts_recorded, incomplete=s.incomplete)
        if s.reasons:
            gaps = ", ".join(f"{powod} ×{n}" for powod, n in s.reasons.items())
            linia += i18n.t("pipeline.fmt.calibrate_gaps", gaps=gaps)
        return linia

    def _format_lineage(self, s):
        """Linia raportu rodowodu. Powiązania per relacja (dark/flat) + „czego brakuje" wypisane
        (nie tylko liczba): luka to jedyna informacja, którą user może tu wynieść — który light
        nie ma kalibratora i dlaczego. Zerowe luki milczą (QUIET)."""
        linked = " · ".join(f"{rel} {s.linked.get(rel, 0)}" for rel in ("dark", "flat"))
        linia = i18n.t("pipeline.fmt.lineage", lights=s.lights, linked=linked)
        if s.reasons:
            gaps = ", ".join(f"{powod} ×{n}" for powod, n in s.reasons.items())
            linia += i18n.t("pipeline.fmt.lineage_gaps", gaps=gaps)
        return linia

    def _format_delta(self, r):
        total = r.object_resolved + r.object_unresolved
        top = ", ".join(f"{raw}×{n}" for raw, n in r.object_delta[:8]) or i18n.t("pipeline.delta.none")
        # Populacja RAW dokleja się do TEJ SAMEJ pozycji, a nie do własnej linii: to ten sam objaw
        # (klatka bez nazwy), inna droga naprawy — rozdzielenie na dwa wiersze sugerowałoby dwa
        # niezależne problemy. Milczy przy zerze (archiwum bez lustrzanki).
        nameless = str(r.object_nameless)
        if r.object_nameless_raw:
            nameless += i18n.t("pipeline.delta.nameless_raw", n=r.object_nameless_raw)
        if r.object_nameless_stacks:
            nameless += i18n.t("pipeline.delta.nameless_stacks", n=r.object_nameless_stacks)
        # Druga strona zawężenia procentu: klatki Z obiektem, ale BEZ nazwy w nagłówku, stoją poza
        # ułamkiem po obu stronach. Bez tej doklejki licznik po prostu spada i ekran nie tłumaczy
        # dlaczego — a Horreum jest aplikacją okienkową, więc CLI tego nie wyjaśni za niego.
        no_raw = (i18n.t("pipeline.delta.resolved_no_raw", n=r.object_resolved_no_raw)
                  if r.object_resolved_no_raw else "")
        # NAGROBEK DOKLEJA SIĘ DWIEMA LICZBAMI, KAŻDA DO SWOJEGO ZDANIA (recenzja + wizytacja S3).
        # Jedna liczba na dwie populacje dawała zdanie arytmetycznie fałszywe: „bez nazwy
        # w nagłówku: 0 · z tego cofnięte ręką: 16", bo 7 z tych 16 miało nazwę i stało wierszem
        # wyżej. „Z tego" wolno napisać wyłącznie o PODZBIORZE liczby, przy której stoi.
        if r.object_cleared_named:
            top += i18n.t("pipeline.delta.cleared_named", n=r.object_cleared_named)
        if r.object_cleared_nameless:
            nameless += i18n.t("pipeline.delta.cleared_nameless", n=r.object_cleared_nameless)
        return i18n.t(
            "pipeline.fmt.delta", resolved=r.object_resolved, total=total, pct=r.object_pct,
            filters=r.filters_canon, top=top, review=_review_line(r.review),
            nameless=nameless, no_raw=no_raw)

    def _refresh_buttons(self, running, cancellable):
        idle = not running
        has_db = self._db_path is not None
        self.btn_receive.setEnabled(idle and has_db)   # katalog niepotrzebny — przynosi własny (F5)
        self.btn_pick.setEnabled(idle)
        self.combo_tier.setEnabled(idle)
        self.btn_all.setEnabled(idle and self._can_scan())
        self.btn_scan.setEnabled(idle and self._can_scan())
        self.btn_group.setEnabled(idle and has_db)
        self.btn_resolve.setEnabled(idle and has_db)
        self.btn_calibrate.setEnabled(idle and has_db)
        self.btn_lineage.setEnabled(idle and has_db)
        self.btn_delta.setEnabled(idle and has_db)
        self.btn_presence.setEnabled(idle and self._can_scan())   # potrzebuje drzewa, nie samej bazy
        # Stosy przynoszą WŁASNY korzeń (dialog), więc jak „Przyjmij nowe" nie zależą od `_root`
        # trybu zaawansowanego — wymagają samej bazy.
        self.btn_stacks.setEnabled(idle and has_db)
        self.btn_stack_lineage.setEnabled(idle and has_db)
        self.btn_mark_vanished.setEnabled(idle and self._presence_params is not None)
        self.btn_cancel.setEnabled(running and cancellable)

    def _set_running(self, running, *, cancellable=False):
        # Pasek żyje TYLKO w trakcie przebiegu: „100%" po zakończeniu jest największym elementem
        # ekranu i przejmuje uwagę od zdania, które faktycznie coś mówi (wizytator P5 #6).
        if not running:
            self.bar.setVisible(False)
        self._cancellable = cancellable if running else False
        self._refresh_buttons(running, self._cancellable)
        self.running_changed.emit(running)

    def _can_scan(self):
        return self._db_path is not None and self._root is not None

    def _sync_actions(self):
        self._refresh_buttons(self._thread is not None, self._cancellable)

# --- TODO-DŁUG (z kolejki sesji, dieta 2026-08-10; pełne brzmienia: archiwum aa) ---
# TODO-DŁUG(E4-7): raport niekompletnego przebiegu mówi ILE, nie KTÓRE - ścieżki nieprzeczytanych
#   katalogów ma tylko CLI, a wydanie onefile CLI nie ma. Nośnik jak box_vanished: sekcja przy
#   niezerowej liście + akcja „skanuj ponownie"; jeden właściciel dla GUI i _format_stacks.
