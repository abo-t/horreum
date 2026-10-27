"""Wspólny WYKONAWCA writebacku off-thread — worker + uchwyt startu/sprzątania dla KAŻDEJ
powierzchni, która commituje albo cofa zmiany plików (P-D/D-PD-3).

Do P-D mieszkał w `grid.py` i był prywatny dla „Zbiorów". Druga powierzchnia (dialog „Napraw
nagłówek…" osi obiektu) potrzebuje tego samego cyklu, a SKOPIOWANIE klasy powieliłoby naprawę
deadlocku AB-BA (GIL × `~QThread`, 2026-07-20), która raz już kosztowała sesję debugowania —
dlatego wędruje TU cały zestaw: worker, dyspozycja `_OPS`, fallback inline dla `:memory:`
i cleanup z `wait()`.

Warstwa widżetów (import Qt uprawniony), ale worker ŻADNEGO widżetu nie dotyka: postęp/koniec/błąd
wracają sygnałami, a wołający sam gasi przyciski i rysuje pasek - dlatego w `grid.py` zostaje
kilkulinijkowy launcher robiący WYŁĄCZNIE rzeczy widżetowe. Jedyny widżet modułu to pole zdania okien
zapisu (`EtykietaBledu`, AR-185, AR-204): jeden protokół „zdanie + szczegół” dla okien, które biorą
stąd zdania wyniku, szuflady Zbiorów, notek żniw i pól błędu stron.

Uchwyt jest PER POWIERZCHNIA, nie singleton: wspólna instancja zlałaby `is_busy`, `cancel()`
i callbacki dwóch niezależnych operacji. Wzajemne wykluczenie DWÓCH powierzchni jest więc
osobnym faktem i mieszka w gospodarzu (`MainWindow`) — patrz `app.py`.
"""

from __future__ import annotations

import dataclasses
import inspect
import re
import string
import threading

from PySide6.QtCore import QObject, QRect, QSize, Qt, QThread, Signal, Slot
from PySide6.QtGui import QGuiApplication, QKeySequence, QPainter
from PySide6.QtWidgets import QLabel, QMenu

from horreum import db, lead_copy, writeback
from horreum.gui import i18n
from horreum.item_reasons import (SYSTEM_REASON_CODES, PowodPozycji,   # powód z kodem (AR-141)
                                  param_ok, powod_okna)
from horreum.gui.i18n_catalog import CATALOG


@dataclasses.dataclass(frozen=True)
class InplaceGestureResult:
    """Wynik pętli gestu izolacji zapisu w miejscu: `writeback.FileResult` per operacja, w kolejności
    celu, i czy człowiek przerwał pętlę (operacje po przerwaniu nietknięte)."""
    results: list
    cancelled: bool = False


def po_operacjach(con, op_ids, now, progress, should_cancel, krok):
    """Pętla gestu izolacji po liście `inplace_op.id` (gesty „Dokończ zapis" / „Przywróć nagłówek
    sprzed zapisu" / „Zwolnij plik do skanu…" w Zbiorach). `krok` = `writeback.finish_inplace`,
    `writeback.recover_torn` albo `writeback.release_isolation` z powodem człowieka:
    każdy działa pod własną blokadą pliku i własną transakcją, więc przerwanie MIĘDZY operacjami
    zostawia stan spójny. Anulowanie sprawdzane PRZED każdą operacją, jak w commicie; postęp po
    każdej, ze statusem rdzenia."""
    wyniki = []
    for i, op_id in enumerate(op_ids, start=1):
        if should_cancel():
            return InplaceGestureResult(wyniki, cancelled=True)
        wynik = krok(con, op_id, now=now)
        wyniki.append(wynik)
        progress(i, len(op_ids), wynik.path, wynik.status)
    return InplaceGestureResult(wyniki)


def _zapis_kart(con, run_id, now, progress, should_cancel):
    """Zapis kart przebiegu W MIEJSCU ze spadkiem na drogę atomową z powodem - jedna operacja dla
    szuflady Zbiorów i okien kart (AR-117, AR-161)."""
    return writeback.commit(con, run_id, now=now, progress=progress, should_cancel=should_cancel,
                            inplace=True)


@dataclasses.dataclass(frozen=True)
class CzescZapisu:
    """FAKTY operacji zapisu kart albo nazw (`WritebackWorker.czesciowy`, AR-322, AR-344, AR-345) - liczone
    przez wykonawcę na własnym połączeniu PO operacji, udanej i nieudanej, każde pole w osłonie (odczyt, który
    sam padnie, daje pole „nieznane”, nie zmienia wyniku operacji):

      * `applied` - ścieżki z postępu rdzenia ze statusem zapisu (`applied`, `withheld`) - dolna granica;
        plik, po którym wyjątek padł przed postępem, tu nie wchodzi;
      * `wszystkie` - pliki operacji: lokacje czekających wpisów przebiegu PRZED pierwszym zapisem (postęp
        przychodzi dopiero po pliku, więc awaria na pierwszym pliku nie miałaby źródła tej liczby);
      * `zapisane`, `do_sprawdzenia`, `otwarte` - pliki commitów TEJ operacji (delta commitów przebiegu)
        w klasach rdzenia (`writeback.zakresy_cofniecia`); `zapisane` None - odczyt padł (zdanie mówi
        wtedy „co najmniej” z `applied`); nazwy: `zapisane` = nowe wiersze `applied`;
      * `zakres` - zakres „Cofnij” przebiegu kart (`writeback.ZakresCofniecia` albo None) i `zakres_znany` -
        czy odczyt się udał (None przy udanym odczycie znaczy „nie ma czego cofać”);
      * `czeka` - wpisy `pending` przebiegu po operacji; `nazwy` - wiersze `applied` przebiegu nazw (cel
        „Cofnij” nazw); None - odczyt padł."""
    applied: tuple
    wszystkie: int | None = None
    zapisane: int | None = None
    do_sprawdzenia: int = 0
    otwarte: int = 0
    zakres: object = None
    zakres_znany: bool = False
    czeka: int | None = None
    nazwy: int | None = None


class WritebackWorker(QObject):
    """Wykonawca commitu/undo writebacku w wątku tła — bliźniak `PipelineWorker` (pipeline.py §4).
    Otwiera WŁASNE połączenie w SWOIM wątku (`db.connect`; sqlite `check_same_thread` — połączenia
    nie dzielimy między wątkami) i woła Qt-wolny rdzeń `writeback.*` z callbackami `progress`/
    `should_cancel`. NIE dotyka widżetów. Rdzeń commituje per-plik → anulowanie (`Event`) albo wyjątek
    zostawia czysty stan applied/pending (utrwalony). Połączenie zamykane PRZED emisją `done`, żeby
    slot głównego wątku czytał tylko przez `self.con` (bez nakładania połączeń na tym samym pliku)."""

    progress = Signal(int, int, str, str)   # done, total, path, status — MID-commit (Qt-wolny callback rdzenia)
    done = Signal(str, object)              # op, result (CommitResult|UndoResult|InplaceGestureResult|ObjectChangeResult) - niemutowany po zwrocie rdzenia
    # op, zdanie, podpowiedź - wyjątek → sygnał, NIE crash apki; podpowiedź = `wiersz_systemu` powodu
    # z `powod_okna`: szczegół systemu przy błędzie systemu albo bazy klasą (AR-185), „Szczegół
    # techniczny” z `Typ: opis @ horreum/<plik>.py:<linia>` przy błędzie programu (AR-263), "" przy
    # powodzie bez klasy i bez szczegółu (tekst systemu, odmowa z kodem bez błędu systemu w drzewie)
    failed = Signal(str, str, str)
    finished = Signal()                     # run() wrócił KAŻDĄ drogą → quit wątku

    # Pętle po plikach dzielą sygnaturę (con, target_id, now=, progress=, should_cancel=); gest
    # kopii wiodącej bierze ją bez postępu i bez anulowania (jeden plik).
    # Trzy pętle za cofnięciem renamu to gesty izolacji zapisu w miejscu: cel = LISTA `inplace_op.id`, wynik
    # `InplaceGestureResult` (AR-17 (2) - ten sam uchwyt, więc ten sam mutex „writeback → Dostawa").
    # Zwolnienie ręką niesie też POWÓD człowieka, więc jego cel to `{"ops": [...], "reason": ...}`;
    # idzie tym uchwytem, bo rdzeń bierze blokadę pliku (`writeback.release_isolation`) i może na
    # nią czekać - w wątku okna byłoby to zamrożenie, a poza uchwytem - drugi pisarz obok zapisu.
    # Zapis kart i dwa wpisy fali zmiany obiektu (AR-17 krok 3, AR-117) - ta sama sygnatura pętli po
    # plikach: `commit` to karta zapisana W MIEJSCU (spadek na drogę atomową z powodem w
    # `FileResult.reason`), bo pełne przepisanie pliku po SMB zrywa dowiązania `_WBPP` - JEDNA operacja
    # szuflady Zbiorów i okien kart (AR-161, AR-258: dawny alias `commit_inplace` okien zniknął);
    # `object_change` i `undo_object_change` to JEDNA operacja gestu (przeniesienie + karta + baza per
    # pozycja), bo dwa starty uchwytu zwalniałyby między sobą mutex „zapis → Dostawa”. Cel wszystkich
    # trzech: `run_id` przebiegu ze stagingu.
    _OPS = {
        "commit":        _zapis_kart,
        "object_change": lambda con, t, now, pr, sc: writeback.commit_object_change(
            con, t, now=now, progress=pr, should_cancel=sc),
        "undo_object_change": lambda con, t, now, pr, sc: writeback.undo_object_change(
            con, t, now=now, progress=pr, should_cancel=sc),
        "commit_rename": lambda con, t, now, pr, sc: writeback.commit_renames(con, t, now=now, progress=pr, should_cancel=sc),
        "undo":          lambda con, t, now, pr, sc: writeback.undo(con, t, now=now, progress=pr, should_cancel=sc),
        # „Cofnij” szuflady Zbiorów (AR-345): cel = krotka commitów przebiegu zamrożona przy postawieniu przycisku.
        "undo_run":      lambda con, t, now, pr, sc: writeback.undo_run(con, t, now=now, progress=pr,
                                                                        should_cancel=sc),
        "undo_rename":   lambda con, t, now, pr, sc: writeback.undo_renames(con, t, now=now, progress=pr, should_cancel=sc),
        "finish_inplace": lambda con, t, now, pr, sc: po_operacjach(con, t, now, pr, sc, writeback.finish_inplace),
        "recover_torn":   lambda con, t, now, pr, sc: po_operacjach(con, t, now, pr, sc, writeback.recover_torn),
        "release_inplace": lambda con, t, now, pr, sc: po_operacjach(
            con, t["ops"], now, pr, sc,
            lambda c, op_id, *, now: writeback.release_isolation(c, op_id, now=now, reason=t["reason"])),
        # Gest „Ta kopia prowadzi" (AR-4, AR-23): cel = `location.id` wskazanej kopii, wynik
        # `lead_copy.LeadCopyResult`. Plik nie jest pisany, ale CZYTANY (bywa na udziale SMB), więc
        # nie na wątku okna - a tym uchwytem, bo dziedziczy mutex „zapis → Dostawa": przejęcie
        # i pochodne piszą do wierszy, które etap Dostawy właśnie przelicza.
        # Cel to `location_id` albo para `(location_id, frame_id)` - klatka z menu gestu (Z6): skan
        # mógł przepiąć ścieżkę na inną klatkę między menu a zapisem, a ręka nie ma prawa trafić
        # w klatkę, której człowiek nie wybierał (werdykt `raced`, `lead_copy.adopt_lead_copy`).
        "lead_copy": lambda con, t, now, pr, sc: (
            lead_copy.lead_copy_gesture(con, t[0], now, expected_frame_id=t[1])
            if isinstance(t, tuple) else lead_copy.lead_copy_gesture(con, t, now)),
    }

    # FAKTY operacji zapisu (AR-322, AR-344, AR-345): op + `CzescZapisu` - emitowane PRZED `done` i PRZED `failed`
    # (ten sam wątek → ta sama kolejność u odbiorcy), wyłącznie dla `commit`/`commit_rename`. Odbiorca zużywa je
    # raz, w ogonie TEJ operacji. Osobny sygnał, nie czwarty parametr `failed`: `start` pinuje arność odbiorcy
    # porażki (3), a PySide przycina argumenty po cichu - ośmiu odbiorców zgubiłoby go bez błędu.
    czesciowy = Signal(str, object)

    def __init__(self, db_path, op, target_id, *, now_fn):
        super().__init__()
        self._db_path = db_path
        self._op = op
        self._target_id = target_id
        self._now = now_fn
        self._cancel = threading.Event()
        self._podmienione = []                  # ścieżki z postępu rdzenia ze statusem zapisu (TA operacja)

    def request_cancel(self):
        """Kooperatywne anulowanie — stawiane w GŁÓWNYM wątku, czytane w workerze (`Event` bezpieczny
        międzywątkowo; rdzeń sprawdza PRZED każdym plikiem, zostawiając zapisane 'applied')."""
        self._cancel.set()

    @Slot()
    def run(self):
        con = None
        result = None
        error = podpowiedz = czesc = przed = None
        try:
            con = db.connect(self._db_path)     # WŁASNE połączenie w TYM wątku (baza już zmigrowana)
            przed = self._przed_operacja(con)
            result = self._OPS[self._op](con, self._target_id, self._now(),
                                         self._emit_progress, self._cancel.is_set)
        except Exception as exc:                # błąd → sygnał, NIE crash
            # JEDNA reguła wyjątku okna (`item_reasons.powod_okna`, AR-263) - ta sama co w planerze,
            # wydaniu i zmianie obiektu: odmowa klingi z kodem (`OdmowaZPowodem.powod` - ucieka np.
            # z gestu kopii wiodącej przez pochodne, `derive.run_derived` → resolver →
            # `repo.upsert_object`) mówi swoim kodem; błąd systemu i bazy - klasą w języku UI (AR-168),
            # surowy tekst systemu trzecim argumentem do podpowiedzi odbiorcy (AR-185); każdy inny
            # wyjątek (EXPECT rdzenia, `KeyError`, API bazy wbrew kontraktowi) - błąd programu
            # w języku UI, a `Typ: opis @ horreum/<plik>.py:<linia>` w podpowiedzi (AR-237). Dawniej
            # szedł surowym `ValueError: …` w zdaniu, po polsku także w UI EN (wizytacja natywna).
            powod = powod_okna(exc)
            error, podpowiedz = tekst_powodu(powod), wiersz_systemu(powod)
        try:
            if con is not None and przed is not None:
                czesc = self._czesc_zapisu(con, przed)
        finally:
            if con is not None:
                con.close()                     # zamknij PRZED done — main czyta tylko przez self.con
        if czesc is not None:
            self.czesciowy.emit(self._op, czesc)
        if error is not None:
            self.failed.emit(self._op, error, podpowiedz)
        else:
            self.done.emit(self._op, result)
        self.finished.emit()                    # zawsze: zwolnij wątek

    def _emit_progress(self, done, total, path, status):
        # wołane SYNCHRONICZNIE w wątku workera przez rdzeń; ~7 plików/s (I/O NAS) → emisja per plik tania
        # rdzeń raportuje status PO pliku - plik w biegu się nie liczy; `withheld` to plik ZAPISANY (AR-82)
        if status in ("applied", "withheld"):
            self._podmienione.append(path)
        self.progress.emit(done, total, path, status)

    def _przed_operacja(self, con):
        """Stan przebiegu PRZED operacją zapisu (`commit`, `commit_rename`), albo None dla innych operacji:
        `(znane, wszystkie)` - id commitów kart z podmienionym plikiem (nazwy: id wierszy `applied`) do delty
        TEJ operacji i liczba plików operacji (lokacje czekających wpisów - tyle grup przechodzi rdzeń,
        `writeback.commit`, `writeback.commit_renames`). Liczona przed pierwszym zapisem: postęp przychodzi
        dopiero po pliku, a awaria na pierwszym pliku nie dałaby żadnego. Błąd odczytu - błąd operacji
        przed jakimkolwiek zapisem (jak każdy wyjątek tej osłony)."""
        if self._op == "commit":
            czeka = {r["location_id"] for r in writeback.pending_for_run(con, self._target_id)
                     if r["status"] == "pending"}
            return set(writeback.commity_przebiegu(con, self._target_id)), len(czeka)
        if self._op == "commit_rename":
            wiersze = writeback.renames_for_run(con, self._target_id)
            return ({r["id"] for r in wiersze if r["status"] == "applied"},
                    sum(1 for r in wiersze if r["status"] == "pending"))
        return None

    def _czesc_zapisu(self, con, przed):
        """`CzescZapisu` operacji zapisu - z BAZY, na połączeniu wykonawcy, po operacji udanej i nieudanej.
        Karty: pliki commitów TEJ operacji (delta względem `przed`) w klasach rdzenia, zakres „Cofnij” całego
        przebiegu i czekające wpisy; nazwy: nowe wiersze `applied`, wiersze `applied` przebiegu i czekające.
        Każdy odczyt w osłonie - odczyt, który sam padnie (baza pod wyjątkiem), daje pole „nieznane”
        i nie zmienia wyniku operacji."""
        znane, wszystkie = przed
        podmienione = tuple(self._podmienione)

        def _albo_none(odczyt):
            try:
                return odczyt()
            except Exception:  # noqa: BLE001 - fakt nieznany, porażka operacji bez zmian
                return None

        if self._op == "commit_rename":
            wiersze = _albo_none(lambda: writeback.renames_for_run(con, self._target_id))
            if wiersze is None:
                return CzescZapisu(podmienione, wszystkie)
            return CzescZapisu(
                podmienione, wszystkie,
                zapisane=sum(1 for r in wiersze if r["status"] == "applied" and r["id"] not in znane),
                czeka=sum(1 for r in wiersze if r["status"] == "pending"),
                nazwy=sum(1 for r in wiersze if r["status"] == "applied"))
        # JEDNA MIGAWKA (AR-359): trzy odczyty kart w jednej transakcji odczytu - zapis innego połączenia między nimi
        # (drugie okno, CLI) nie złoży pary „commity sprzed - klasy po”, która nigdy nie istniała. Własna transakcja
        # zamykana wycofaniem; połączenie w transakcji (wyjątek operacji w połowie) - odczyty w niej, jak
        # `writeback._klasy_przebiegu`. `BEGIN`, który sam padnie, zostawia odczyty bez migawki (każdy w osłonie).
        wlasna = not con.in_transaction and _albo_none(lambda: con.execute("BEGIN")) is not None
        try:
            nowe = _albo_none(lambda: set(writeback.commity_przebiegu(con, self._target_id)) - znane)
            # Jedna klasyfikacja backupów przebiegu: zakres „Cofnij” całości i pliki commitów TEJ operacji.
            zakresy = _albo_none(lambda: writeback.zakresy_cofniecia(con, self._target_id, nowe or ()))
            czeka = _albo_none(lambda: sum(1 for r in writeback.pending_for_run(con, self._target_id)
                                           if r["status"] == "pending"))
        finally:
            if wlasna:
                _albo_none(con.rollback)                # odczyt - nic do zatwierdzenia
        pola = {"zapisane": None}
        if nowe is not None and zakresy is not None:
            z = zakresy[1]
            pola = {"zapisane": z.zatwierdzone if z else 0, "do_sprawdzenia": z.do_sprawdzenia if z else 0,
                    "otwarte": z.otwarte if z else 0}
        return CzescZapisu(podmienione, wszystkie, zakres=zakresy[0] if zakresy else None,
                           zakres_znany=zakresy is not None, czeka=czeka, **pola)


class WritebackRunner(QObject):
    """Uchwyt cyklu życia jednej powierzchni: worker + wątek + sprzątanie. KLASA (nie mixin, nie goła
    funkcja): mixin kłóciłby się o MRO z `QDialog`/`QWidget` wołającego, a goła funkcja nie ma gdzie
    trzymać referencji — GC zabiłby `QThread` w locie.

    `async_ok=False` (testy) albo brak pliku bazy (`:memory:`) → `run()` INLINE, sygnały direct,
    czyli synchronicznie: ten sam rdzeń, bez QThread. To seam testowy — wołający wystawia go dalej
    jako własną właściwość, bo testy ustawiają go Z ZEWNĄTRZ na widoku.

    `busy_changed` jest JEDNYM właścicielem faktu „ta powierzchnia pisze" — stąd bierze go mutex
    dwóch powierzchni w gospodarzu. Gdyby wołający emitował go sam, musiałby trafić PIĘĆ ścieżek
    końca operacji (commit/undo × klinga + błąd) i pierwsza przeoczona zostawiłaby drugą
    powierzchnię wygaszoną na zawsze."""

    busy_changed = Signal(bool)   # True przy starcie, False gdy operacja skończona (OBIE drogi)

    def __init__(self, db_path, *, now_fn, parent=None):
        super().__init__(parent)
        self._db_path = db_path
        self._now = now_fn
        self.async_ok = True
        self._thread = None
        self._worker = None

    @property
    def is_busy(self):
        """Czy operacja trwa. Guard „jeden writeback naraz" JEDNEJ powierzchni — dwie powierzchnie
        wyklucza gospodarz (uchwyt jest per-powierzchnia, D-PD-3)."""
        return self._thread is not None

    def start(self, op, target_id, *, on_progress, on_done, on_failed, on_partial=None) -> bool:
        """Odpal `op` (klucz `WritebackWorker._OPS`) na `target_id`. Zwraca False, gdy
        operacja już trwa (wołający nie ma wtedy prawa liczyć na callbacki). Sloty dostaje wołający
        - TEN moduł nie wie, co jest paskiem, a co przyciskiem. `on_failed(op, zdanie, podpowiedź)`:
        trzy parametry - PySide przycina argumenty sygnału po cichu, więc odbiorca z dwoma zgubiłby
        szczegół systemu bez błędu (AR-185). Zła arność odbiorcy = `TypeError` od razu (EXPECT),
        nie cisza dopiero przy pierwszej awarii; odbiorca bez sygnatury do sprawdzenia (wbudowany,
        np. `max`) - też `TypeError`: arności nie da się dowieść. Sprawdzenie stoi ZA zajętością -
        operacja w biegu odpowiada `False` każdemu wołającemu (wołający nie dostaje wtedy callbacków).
        `on_partial(op, CzescZapisu)` (opcjonalny, AR-322): wynik częściowy zapisu, który padł po podmianie
        plików - przychodzi PRZED `on_failed` tej samej operacji; METODA obiektu Qt (kolejka, wątek okna)."""
        if self._thread is not None:
            return False
        try:
            sygnatura = inspect.signature(on_failed)
        except ValueError as exc:
            raise TypeError(f"odbiorca porażki bez sygnatury do sprawdzenia: {on_failed!r}") from exc
        sygnatura.bind("op", "zdanie", "podpowiedź")
        self._worker = WritebackWorker(self._db_path, op, target_id, now_fn=self._now)
        self._worker.progress.connect(on_progress)
        self._worker.done.connect(on_done)
        self._worker.failed.connect(on_failed)
        if on_partial is not None:
            self._worker.czesciowy.connect(on_partial)
        self.busy_changed.emit(True)
        if self.async_ok and self._db_path:
            self._thread = QThread(self)
            self._worker.moveToThread(self._thread)
            self._thread.started.connect(self._worker.run)
            self._worker.finished.connect(self._thread.quit)
            self._thread.finished.connect(self._cleanup)
            self._thread.start()
        else:
            try:
                self._worker.run()              # inline: done/progress lecą direct = synchronicznie
            finally:
                self._worker = None
                self.busy_changed.emit(False)   # inline kończy się TU (nie ma wątku ani cleanupu)
        return True

    def cancel(self):
        """Kooperatywne anulowanie bieżącej operacji (rdzeń sprawdza PRZED następnym plikiem)."""
        if self._worker is not None:
            self._worker.request_cancel()

    def refuse_close(self, say, *, przerwij=True):
        """Straż zamknięcia OKNA-WŁAŚCICIELA tego uchwytu: `True` = operacja trwa, okno ma ZOSTAĆ.

        Uchwyt i jego `QThread` są dziećmi okna, więc zamknięcie okna w biegu niszczyłoby wątek,
        który jeszcze pracuje („QThread: Destroyed while thread is still running" = twardy abort).
        Wzorzec `projection_dialog.done` (wydanie w biegu): zamknięcie = ŻĄDANIE ANULOWANIA, okno
        zostaje - czekanie z timeoutem byłoby zakładem o czas jednego pliku po SMB, a raport
        przerwanego zapisu (ile plików zmieniono, `commit_id` do cofnięcia) musi mieć dokąd trafić.
        Drugie zamknięcie, już po biegu, zamyka. `say(tekst)` = gdzie okno mówi, co się dzieje.
        Jeden kod dla każdego okna z tym uchwytem (SPOT) - nie kopia warunku w każdym `done`.
        `przerwij=False` - sama odmowa bez anulowania (przełączenie bazy gospodarza, AR-296: zamiar
        przerwania zapisu wyraża tylko zamknięcie okna); `say` dostaje wtedy ten sam tekst."""
        if self._thread is None:
            return False
        if przerwij:
            self.cancel()
        say(i18n.t("wb.close_refused"))
        return True

    def _cleanup(self):
        # wait() PRZED thread.deleteLater(): worker.deleteLater() doręcza się w teardown wątku
        # (Shiboken::Object::destroy → PyGILState_Ensure); bez wait() ~QThread mógłby czekać na
        # wątek TRZYMAJĄC GIL → AB-BA deadlock (native dump 2026-07-20, ten sam mechanizm co
        # projection_dialog._cleanup_dry_thread — komentarz tam). wait() zwalnia GIL → wątek
        # dokańcza destrukcję i umiera; ~QThread trafia na martwy handle.
        self._worker.deleteLater(); self._thread.wait(); self._thread.deleteLater()
        self._worker = None; self._thread = None
        self.busy_changed.emit(False)


# ------------------------------------------------ zdania wyniku - wspólne dla KAŻDEJ powierzchni zapisu
# Trzech wołających (szuflada gridu, „Napraw nagłówek…", „Zatwierdź ze ścieżki…") mówiło to samo
# zdanie trzema kopiami, a reguła „kiedy wolno cofnąć" już raz się między nimi rozjechała (Z11).
# Mieszkają TU, bo ten moduł importują wszystkie trzy bez cyklu (`app` → `grid` → `wb_worker`).


def _liczba(klucz, n):
    """Człon liczby zdania wyniku: wpis MNOGI katalogu idzie przez `t_plural` (odmiana 1 / 2-4 /
    5+ / -naście), wpis prosty przez `t` (forma „etykieta: N”, bez odmiany). Rodzinę `grid.wb.*`
    składał dotąd sam `t`, więc „1 zapisanych”, „1 zablokowanych”, „1 błędów” - klucze przeszły
    na wpisy mnogie bez zmiany wołających."""
    if isinstance(CATALOG.get(klucz, {}).get("pl"), dict):
        return i18n.t_plural(klucz, n)
    return i18n.t(klucz, n=n)


def zdanie_wyniku_zapisu(res, noun_key):
    """„N {noun} · M zablokowanych · …" + pierwszy powód błędu/blokady (wiz #4: user na ścianie
    `blocked` pyta „czemu?", nie chce samego licznika). `noun_key` = klucz frazy głównej
    (`grid.wb.applied`/`grid.wb.renamed`/`path.cards_applied`) - DANE, nie string PL.

    Powód BŁĘDU ma pierwszeństwo przed powodem blokady: blokada zostawia plik nietknięty, a błąd
    bywa rozjazdem, który trzeba naprawić („plik PRZENIESIONY…, baza NIE przepięta - zamiar renamu
    zapisany: ponowienie albo cofnięcie przebiegu dokończy przepięcie"). Przy odwrotnej kolejności jedna blokada w tym samym wsadzie chowała go za sobą.

    RÓŻNE POWODY (AR-162): „2 zablokowane - plik zmieniony od ostatniego skanu” przy blokadach
    z dwóch różnych powodów brzmiało jak powód wspólny. Gdy pozycje z powodem mają powody różne
    (`_klucz_powodu`: po kodzie, bez kodu po tekście), zdanie mówi „pierwszy z N różnych powodów:
    …” - bez słownika krótkich nazw per kod, którego katalog nie ma. Reszta powodów stoi tam, gdzie
    powierzchnia je ma: przy pozycjach (kolumna Status „Zmień obiekt…”), a w oknach kart bez listy
    pozycji - w podpowiedzi zdania (`podpowiedz_powodow`, zdanie odsyła do niej:
    `zdanie_commitu_kart`). Jeden powód albo same jednakowe - zdanie znak w znak."""
    parts = [_liczba(noun_key, len(res.applied))]
    wstrzymane = _wstrzymane_poza_zapisanymi(res)
    if wstrzymane:
        parts.append(_liczba("grid.wb.withheld", len(wstrzymane)))
    if res.blocked:
        parts.append(_liczba("grid.wb.blocked", len(res.blocked)))
    if res.failed:
        parts.append(_liczba("grid.wb.errors", len(res.failed)))
    if res.skipped:
        parts.append(_liczba("grid.wb.skipped", len(res.skipped)))
    summary = " · ".join(parts)
    rozne = _rozne_powody(res)
    if rozne:
        detail = tekst_powodu(rozne[0].reason)
        if len(rozne) > 1:
            detail = i18n.t("wb.reasons_first", n=len(rozne), detail=detail)
        summary += i18n.t("grid.wb.detail_sep", detail=detail)
    return summary


def _wstrzymane_poza_zapisanymi(res):
    """AR-82: plik ZAPISANY, a zeznanie klatki go nie przyjęło - osobny człon, nie „0 zapisanych”.
    Przy cofnięciu gestu `withheld` jest podzbiorem `applied` (karta wróciła) - tamto zdanie mówi
    o nim własnym członem (`zdanie_wyniku_zmiany`), tu liczą się tylko pliki spoza `applied`."""
    return [fr for fr in res.withheld if fr not in res.applied]


def _rozne_powody(res):
    """Pierwsza pozycja z KAŻDYM różnym powodem (`_klucz_powodu`), w kolejności zdania: błąd przed
    wstrzymaniem przed blokadą. Pierwsza z listy to powód, który zdanie mówi wprost."""
    widziane, wynik = set(), []
    for fr in res.failed + _wstrzymane_poza_zapisanymi(res) + res.blocked:
        if fr.reason and _klucz_powodu(fr.reason) not in widziane:
            widziane.add(_klucz_powodu(fr.reason))
            wynik.append(fr)
    return wynik


def podpowiedz_powodow(res):
    """Podpowiedź zdania wyniku w oknie BEZ listy pozycji („Napraw nagłówek…”, „Zatwierdź ze
    ścieżki…”): przy różnych powodach - każdy różny powód w języku UI z nazwą pierwszego
    pliku, który go dostał, wiersz na powód; przy jednym powodzie `""` (zdanie mówi go całego)."""
    from horreum.gui.grid_model import _ogon_sciezki   # lazy: `grid_model` woła ten moduł leniwie
    rozne = _rozne_powody(res)
    if len(rozne) < 2:
        return ""
    return "\n".join(i18n.t("wb.reason_line", file=_ogon_sciezki(fr.path),
                            reason=tekst_powodu(fr.reason)) for fr in rozne)


def podpowiedz_kart(res):
    """Podpowiedź zdania commitu okna kart: szczegół spadku na drogę atomową (`podpowiedz_spadku`),
    różne powody blokad/błędów (`podpowiedz_powodow`) i surowy tekst systemu pierwszego błędu
    systemu (`podpowiedz_systemu`, AR-168) - wiersze, które są; `""`, gdy żadnych. Wspólna dla okien
    kart i szuflady Zbiorów."""
    return "\n".join(p for p in (podpowiedz_spadku(res), podpowiedz_powodow(res),
                                 podpowiedz_systemu(res), podpowiedz_operacji(res)) if p)


# Wywołania rdzenia, którymi drogę wyjścia z izolacji domyka programista (AR-281): zdanie mówi gest
# z menu, a numer operacji i wywołanie schodzą do wiersza szczegółu pod kursorem. Kod → funkcje
# `writeback` wołane z `op_id` z parametrów powodu.
_WYWOLANIA_DROGI = {
    "way_finish": ("finish_inplace",), "way_restore": ("recover_torn",),
    "isolated_recover": ("recover_torn",), "isolated_finish": ("finish_inplace", "recover_torn"),
    "finish_failed_isolated_release": ("release_isolation",),
    "undo_commit_unfinished": ("finish_inplace",),
}


def _droga_operacji(powod):
    """`(kod, op_id)` pierwszego powodu drogi z `_WYWOLANIA_DROGI` w drzewie powodu (parametry-powody,
    listy, uwagi) albo None. TOTALNE: `op_id`, który nie jest liczbą (zapis spoza kodeka), pomija."""
    if not isinstance(powod, PowodPozycji):
        return None
    op_id = dict(powod.params).get("op_id")
    if powod.code in _WYWOLANIA_DROGI and isinstance(op_id, int) and not isinstance(op_id, bool):
        return powod.code, op_id
    for _nazwa, wartosc in powod.params:
        for w in (wartosc if isinstance(wartosc, (list, tuple)) else (wartosc,)):
            znaleziony = _droga_operacji(w)
            if znaleziony is not None:
                return znaleziony
    return None


def wiersz_operacji(powod):
    """Wiersz szczegółu „Operacja zapisu w miejscu N: writeback.recover_torn(N)” powodu z drogą
    wyjścia z izolacji (AR-281) albo `""`."""
    znaleziony = _droga_operacji(powod)
    if znaleziony is None:
        return ""
    kod, op_id = znaleziony
    wywolanie = ", ".join(f"writeback.{f}({op_id})" for f in _WYWOLANIA_DROGI[kod])
    return i18n.t("wb.op_detail_tip", op_id=op_id, call=wywolanie)


def podpowiedz_operacji(res):
    """Wiersze `wiersz_operacji` WSZYSTKICH pozycji wyniku z drogą wyjścia, każdy z nazwą pliku
    (`wb.op_detail_line`) - ta sama kolekcja co zdanie wyniku (`_rozne_powody`: błąd, wstrzymanie, blokada),
    bez powtórzeń; `""`, gdy żadna. Dwa izolowane pliki to dwa numery operacji - zdanie numerów nie
    mówi (AR-281), więc pod kursorem nie może zostać tylko pierwszy."""
    from horreum.gui.grid_model import _ogon_sciezki   # lazy: `grid_model` woła ten moduł leniwie
    zapisane = list(getattr(res, "applied", [])) + list(getattr(res, "restored", []))
    wstrzymane = [fr for fr in getattr(res, "withheld", []) if fr not in zapisane]
    wiersze = []
    for fr in res.failed + wstrzymane + res.blocked:
        wiersz = wiersz_operacji(fr.reason)
        if wiersz:
            linia = i18n.t("wb.op_detail_line", file=_ogon_sciezki(fr.path), detail=wiersz)
            if linia not in wiersze:
                wiersze.append(linia)
    return "\n".join(wiersze)


def szczegol_powodu(powod):
    """Wiersze szczegółu JEDNEGO powodu: surowy tekst systemu (`wiersz_systemu`) i numer operacji
    zapisu w miejscu z drogą wyjścia (`wiersz_operacji`, AR-281) - te, które są, albo `""`. Dla
    powierzchni, które dotąd dokładały sam `wiersz_systemu` (pole błędu okna zmiany obiektu, status
    pozycji)."""
    return "\n".join(w for w in (wiersz_systemu(powod), wiersz_operacji(powod)) if w)


def podpowiedz_cofniecia(res):
    """Podpowiedź zdania cofnięcia w oknach kart: szczegół systemu (`podpowiedz_systemu`, AR-168)
    i numery operacji z drogą wyjścia (`podpowiedz_operacji`, AR-281) - wiersze, które są."""
    return "\n".join(p for p in (podpowiedz_systemu(res), podpowiedz_operacji(res)) if p)


def szczegol_systemu(powod):
    """Surowy tekst systemu albo bazy (`Typ: [WinError N] opis`) błędów klasą
    (`item_reasons.SYSTEM_REASON_CODES`) w drzewie powodu - parametry-powody, listy, uwagi - albo
    None. Zdanie mówi klasę i numer w języku UI, komunikat systemu (w języku systemu) schodzi tu.
    Błąd spoza klas z numerem systemu (`OSError: [WinError 87] …`) też: zdanie mówi numer i komunikat
    bez nazwy klasy Pythona (`czytelny_powod`), surowy tekst z klasą stoi tu (AR-388); kilka surowych
    tekstów w drzewie - wiersz pod wierszem (`_surowy_systemu`)."""
    surowe = _surowy_systemu(powod)
    return "\n".join(_bez_repr_sciezek(s) for s in surowe) if surowe else None


def _surowy_systemu(powod):
    """LISTA surowych tekstów systemu w drzewie powodu (parametry-powody, listy, uwagi), w kolejności
    drzewa: `detail` każdego błędu klasą (system, baza) i w węźle tekstowym (powód gołym tekstem, parametr
    `inner`…) KAŻDY surowy wyjątek systemu spoza klas, z którego zdanie zdejmuje nazwę klasy
    (`_surowe_wyjatki`, AR-388) - zajętość 32/33 mówi własne zdanie, bez szczegółu. Bez powtórzeń: wyjątek
    w komunikacie innego (przedział zagnieżdżony w tym samym tekście) - po pozycjach, ten sam tekst - raz
    (równość, nie podciąg: `… a` i `… ab` to dwa wyjątki)."""
    wynik, widziane = [], set()

    def _idz(w):
        if isinstance(w, PowodPozycji):
            if w.code in SYSTEM_REASON_CODES:
                detail = dict(w.params).get("detail")
                teksty = [detail] if isinstance(detail, str) else []
            else:
                for _nazwa, wartosc in w.params:
                    for x in (wartosc if isinstance(wartosc, (list, tuple)) else (wartosc,)):
                        _idz(x)
                return
        elif isinstance(w, str):
            teksty, zasieg = [], -1
            for poczatek, _klasy, koniec, numer in _surowe_wyjatki(w):
                # zajętość; tekst zawarty we wcześniejszym (wyjątek w komunikacie innego) - po pozycjach, bez wycinków
                if numer in _NUMERY_ZAJETOSCI or koniec <= zasieg:
                    continue
                teksty.append(w[poczatek:koniec])
                zasieg = koniec
        else:
            return
        for tekst in teksty:
            if tekst not in widziane:
                widziane.add(tekst)
                wynik.append(tekst)
    _idz(powod)
    return wynik


def wiersz_szczegolu(surowy):
    """Wiersz podpowiedzi „Szczegół systemu: …” z surowego tekstu systemu (ścieżki bez zapisu
    `repr`) albo `""` - JEDNA reguła składania wiersza dla powodu z kodem (`wiersz_systemu`) i dla
    parametru pominięcia planera (`object_change_dialog.podpowiedz_pominiecia`)."""
    return i18n.t("wb.os_detail_tip", detail=_bez_repr_sciezek(surowy)) if surowy else ""


def wiersz_systemu(powod):
    """Wiersz podpowiedzi „Szczegół systemu: …” powodu z błędem systemu klasą (`szczegol_systemu`)
    albo `""` - jeden dla wyniku zapisu, awarii całej operacji (AR-185), kopii wiodącej i okien
    wydania, żniw i zmiany obiektu (AR-184). Wyjątek spoza klas z numerem systemu dostaje swój surowy
    tekst (zdanie zdjęło z niego nazwę klasy, AR-388) - każdy, wiersz na tekst (`_surowy_systemu`); powód
    bez klasy i bez numeru (tekst systemu bez `[WinError N]`/`[Errno N]`, wyjątek spoza systemu) nie dostaje
    wymyślonego szczegółu.

    Błąd PROGRAMU z kodem (`prog_error`, `item_reasons.powod_okna`) to nie błąd systemu (nie stoi
    w `SYSTEM_REASON_CODES`), ale jego zdanie odsyła pod kursor - wiersz „Szczegół techniczny: …”
    z surowym `Typ: opis` z parametru `detail`. TOTALNE jak `_surowy_systemu`: powód odtworzony
    z bazy kodekiem może nie mieć `detail` tekstem - wtedy `""`, nie wyjątek w oknie."""
    if isinstance(powod, PowodPozycji) and powod.code == "prog_error":
        detail = dict(powod.params).get("detail")
        return i18n.t("objchg.st.detail_tip", detail=detail) if isinstance(detail, str) and detail else ""
    return "\n".join(wiersz_szczegolu(s) for s in _surowy_systemu(powod))


def podpowiedz_systemu(res):
    """Wiersze podpowiedzi „Szczegół systemu: …” pozycji wyniku z błędem systemu (błąd przed wstrzymaniem
    przed blokadą, jak w zdaniu wyniku): pierwsza taka pozycja KAŻDEGO różnego powodu (`_klucz_powodu`) -
    zdanie i podpowiedź powodów mówią pierwszą pozycję każdego różnego powodu bez nazwy klasy Pythona,
    więc szczegół niesie każdy z tych surowych tekstów (AR-388); bez powtórzeń wierszy; albo `""`."""
    klucze, wiersze = set(), {}                          # słownik = zbiór z kolejnością dopisania
    for fr in res.failed + list(getattr(res, "withheld", [])) + res.blocked:
        wiersz = wiersz_systemu(fr.reason)
        if not wiersz or _klucz_powodu(fr.reason) in klucze:
            continue
        klucze.add(_klucz_powodu(fr.reason))
        wiersze.update(dict.fromkeys(wiersz.split("\n")))
    return "\n".join(wiersze)


# Miejsce łamania wiersza po `\` w tekście MALOWANYM pola zdania (AR-221): U+200B, niewidoczny
# (zmierzone natywnie: piksele wiersza z nim i bez - identyczne) i dla Qt miejsce łamania.
_LAMANIE = "\N{ZERO WIDTH SPACE}"


class ZdanieZeSzczegolem(str):
    """Zdanie raportu dla paska gospodarza RAZEM ze szczegółem (AR-218): `str` = zdanie (odbiorcy
    sygnału, testy i log widzą je znak w znak - wzorzec `grid_model.Recepta`, `PowodPozycji`),
    `szczegol` = wiersze szczegółu (`wiersz_systemu`, `podpowiedz_*`) albo `""`. Do AR-218 zdanie
    paska po awarii mówiło klasę, a surowy tekst systemu zostawał w polu okna, które się zamknęło,
    albo w szufladzie.

    Nośnik jedzie sygnałem `Signal(object)`: `Signal(str)` zamienia podklasę na goły `str` i szczegół
    przepada po cichu (zmierzone, PySide6 6.9.2). Para dwóch argumentów (`Signal(str, str)`) odpadła,
    bo odbiorca `list.append` dostaje wtedy `TypeError` wypisany na stderr i nie dostaje zdania.
    Konkatenacja zwraca goły `str` - zdania ze szczegółem składa `zlacz_zdania`.

    `polecenie` (AR-309) - samo polecenie wiersza poleceń, które zdanie podaje jako drogę wyjścia
    (cofnięcie commitu kart, przebiegu zmiany obiektu), albo `""`. Osobne pole, nie wiersz szczegółu
    do wyłuskania: pole zdania kopiuje je pozycją „Kopiuj polecenie” znak w znak, a parsowanie prozy
    szczegółu rozjechałoby się z pierwszą zmianą jej brzmienia."""

    def __new__(cls, zdanie, szczegol="", polecenie=""):
        self = super().__new__(cls, zdanie)
        self.szczegol = szczegol or ""
        self.polecenie = polecenie or ""
        return self


def szczegol_zdania(msg):
    """Szczegół zdania raportu (`ZdanieZeSzczegolem.szczegol`) albo `""` dla zwykłego `str` - jeden
    czytelnik nośnika."""
    return msg.szczegol if isinstance(msg, ZdanieZeSzczegolem) else ""


def polecenie_zdania(msg):
    """Polecenie zdania raportu (`ZdanieZeSzczegolem.polecenie`) albo `""` dla zwykłego `str` -
    bliźniak `szczegol_zdania`."""
    return msg.polecenie if isinstance(msg, ZdanieZeSzczegolem) else ""


def zlacz_zdania(sep, zdania):
    """Zdania złączone separatorem, ze szczegółami i poleceniami wszystkich, które je niosą (wiersz
    pod wierszem) - `" - ".join(...)` zgubiłby oba. Puste zdania odpadają. Wejście bywa generatorem,
    więc materializowane RAZ, zanim zdania, szczegóły i polecenia zostaną z niego odczytane."""
    elementy = tuple(z for z in zdania if z)
    return ZdanieZeSzczegolem(sep.join(elementy),
                              "\n".join(s for s in map(szczegol_zdania, elementy) if s),
                              "\n".join(p for p in map(polecenie_zdania, elementy) if p))


class EtykietaBledu(QLabel):
    """Pole zdania okna zapisu - JEDYNY protokół „zdanie + szczegół” (AR-204): pole błędu okien kart,
    zmiany obiektu i stron Dostawy, wynik szuflady Zbiorów (`grid_selection._ZdanieWyniku`), notki
    żniw. Do AR-204 były trzy drogi (`setText` + `setToolTip` z samym szczegółem, `_ustaw_zdanie`
    żniw, `_podpowiedz_wyniku` szuflady) i dwa kształty podpowiedzi.

    `ustaw(zdanie, szczegol)` to jedyna droga zdania ze szczegółem; `setText` i `clear` to `ustaw`
    bez szczegółu, więc zdanie spoza protokołu (walidacja, „brak gospodarza”, postęp szuflady)
    zdejmuje szczegół poprzedniego - szczegół jednej awarii nie stoi pod innym zdaniem. C++ `clear`
    nie woła pythonowego `setText` (zmierzone, PySide6 6.9) - stąd nadpisane oba.

    `text()` = samo zdanie (wołający czytają je jako treść), podpowiedź = zdanie + wiersze szczegółu.
    MINIMUM SZEROKOŚCI 0 (wzorzec `_ZdanieWyniku`): zdanie ze ścieżką (plik zajęty 32/33, kod spoza
    klas) dyktowało minimum pola swoją szerokością; zmierzone natywnie: okno „Napraw nagłówek…”
    596 → 829 px po awarii (×1,6: 864 → 1299 px). Pole bierze szerokość od okna.

    ŚCIEŻKA ŁAMIE SIĘ W MALOWANIU (AR-221): zawijanie Qt łamie wiersz na spacjach i po `/`, a po `\\`
    nie - ścieżka Windows była jednym słowem uciętym na prawej krawędzi pola. Tekst MALOWANY (wewnętrzny
    tekst `QLabel`, z którego Qt liczy też `heightForWidth`) ma po każdym `\\` niewidoczne miejsce
    łamania U+200B; `text()`, podpowiedź, nazwa dostępności i schowek (Ctrl+C, menu) - zdanie bez
    niego. Zmierzone natywnie: najszerszy segment ścieżki kopii archiwum (889 px przy ×1,6 w polu
    842 px) Qt łamie sam na `-`, więc dodatkowe miejsca wewnątrz segmentu nie są potrzebne.

    TEKST ZWYKŁY, NIE `AutoText` (AR-235): zdanie niesie wartości z zewnątrz (nazwa pliku, obiekt
    z nagłówka, tekst wyjątku), a Qt w `AutoText` bierze zdanie z pierwszym `<znacznik>` HTML za tekst
    sformatowany i znacznik znika z ekranu - zmierzone natywnie: `(X:\\L\\<a>.fits)` w polu 247 px
    zamiast 270 px, zaznaczenie całości puste. Formatowania nie niesie żaden tekst pól (katalog i18n:
    zero wartości, które Qt uznałby za HTML), a łamanie ścieżki AR-221 jest to samo - zmierzone
    natywnie: 12 konfiguracji pola (zawijanie, zaznaczalność, pasek, szuflada) × 3 szerokości,
    piksele i wysokości identyczne w obu formatach.

    WSKAŹNIK SZCZEGÓŁU: przy niepustym szczególe glif `wb.detail_marker` w wcięciu przed zdaniem
    (malowany, nie w tekście - `text()` zostaje treścią) i szczegół jako opis dostępności; menu
    prawego kliku kopiuje zdanie albo szczegół (w szczególe stoi plik, który padł). MENU WŁASNE
    MA TEŻ KAŻDE NIEPUSTE POLE NIEZAZNACZALNE (AR-243): takie pole nie ma ani zaznaczenia, ani fokusu
    (Ctrl+C nie ma dokąd trafić), więc ścieżki ze zdania błędu bez szczegółu (plik zajęty, kod spoza
    klas) nie dało się skopiować niczym (wizytacja natywna). Pole zaznaczalne dostaje menu
    własne przy szczególe i przy ścieżce (menu Qt kopiowałoby znak łamania); poza tym menu Qt."""

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._zdanie = ""
        self._pelne = ""                # pełne zdanie, gdy pole pokazuje skrót (`ustaw(pelne=)`)
        self._szczegol = ""
        self._polecenie = ""            # samo polecenie wiersza poleceń ze szczegółu (AR-309)
        self._wciecie = None            # wcięcie sprzed wskaźnika; None = wskaźnik zdjęty
        self._menu = None
        self.setTextFormat(Qt.PlainText)    # zdanie z `<…>` nie jest HTML-em (AR-235)
        self.ustaw(text)

    def ustaw(self, zdanie, szczegol="", *, pelne=None, polecenie=""):
        """Zdanie i jego szczegół (wiersze `wiersz_systemu`/`podpowiedz_*`) - razem albo wcale:
        szczegół bez zdania nie ma do czego należeć. `pelne` - pełne zdanie, gdy pole pokazuje skrót
        (raport paska gospodarza przycięty do zapasu paska, AR-218): podpowiedź i „Kopiuj zdanie”
        biorą pełne, `text()` - to, co pole pokazuje.

        `polecenie` (AR-309) - SAMO polecenie wiersza poleceń, które szczegół niesie obok prozy
        (`horreum header-fix "…" --undo N`): menu pola dostaje „Kopiuj polecenie”, bo „Kopiuj szczegół”
        oddawał prozę z poleceniem, a wklejona do terminala proza pada pierwsza. Nośnik podaje je
        osobno - pole nie zgaduje, która linia szczegółu jest poleceniem. Jak szczegół: tylko przy
        niepustym zdaniu, a `setText`/`clear` je zdejmują."""
        zdanie = zdanie or ""
        self._zdanie = zdanie
        self._pelne = (pelne or zdanie) if zdanie else ""
        self._szczegol = (szczegol or "") if zdanie else ""
        self._polecenie = (polecenie or "") if zdanie else ""
        super().setText(zdanie.replace("\\", "\\" + _LAMANIE))
        self.setToolTip("\n".join(p for p in (self._pelne, self._szczegol) if p))
        self.setAccessibleName(self._pelne)
        self.setAccessibleDescription(self._szczegol)
        self._sync_wskaznika()

    def text(self):
        """Zdanie bez miejsc łamania tekstu malowanego (AR-221)."""
        return self._zdanie

    def selectedText(self):
        return super().selectedText().replace(_LAMANIE, "")

    def szczegol(self):
        """Szczegół BIEŻĄCEGO zdania albo `""`."""
        return self._szczegol

    def polecenie(self):
        """Polecenie wiersza poleceń BIEŻĄCEGO zdania (`ustaw(polecenie=)`, AR-309) albo `""`."""
        return self._polecenie

    def setText(self, text):
        self.ustaw(text)

    def clear(self):
        self.ustaw("")

    def keyPressEvent(self, event):
        # Ctrl+C na polu zaznaczalnym: kontrolka Qt skopiowałaby zaznaczenie z miejscami łamania.
        if event.matches(QKeySequence.Copy) and self.hasSelectedText():
            QGuiApplication.clipboard().setText(self.selectedText())
            event.accept()
            return
        super().keyPressEvent(event)

    def minimumSizeHint(self):
        return QSize(0, super().minimumSizeHint().height())

    def _szerokosc_wskaznika(self):
        fm = self.fontMetrics()
        return fm.horizontalAdvance(i18n.t("wb.detail_marker")) + fm.horizontalAdvance(" ")

    def _sync_wskaznika(self):
        """Wcięcie tekstu pod glif - tylko przy zmianie stanu (postęp szuflady woła `setText`
        kilka razy na sekundę). `indent`, nie marginesy: marginesów pilnuje arkusz stylu."""
        if self._szczegol and self._wciecie is None:
            self._wciecie = self.indent()
            self.setIndent(self._szerokosc_wskaznika())
        elif not self._szczegol and self._wciecie is not None:
            self.setIndent(self._wciecie)
            self._wciecie = None

    def _prostokat_tekstu(self):
        """Prostokąt zdania - `contentsRect` bez wcięcia wskaźnika (dla malujących zdanie sami)."""
        r = self.contentsRect()
        return r.adjusted(self.indent(), 0, 0, 0) if self._wciecie is not None else r

    def _maluj_wskaznik(self, painter):
        """Glif w wcięciu, na wysokości pierwszego wiersza zdania, kolorem zdania (rola pola)."""
        if self._wciecie is None:
            return
        r = self.contentsRect()
        fm = self.fontMetrics()
        pion = self.alignment() & Qt.AlignVertical_Mask
        gora = r.top()
        if pion & Qt.AlignVCenter:
            flagi = int(self.alignment()) | (Qt.TextWordWrap.value if self.wordWrap() else 0)
            blok = fm.boundingRect(self._prostokat_tekstu(), flagi, super().text())   # malowany
            gora = r.top() + max(0, (r.height() - blok.height()) // 2)
        elif pion & Qt.AlignBottom:
            gora = r.bottom() - fm.height()
        self.style().drawItemText(painter, QRect(r.left(), gora, self.indent(), fm.height()),
                                  int(Qt.AlignLeft | Qt.AlignTop), self.palette(), self.isEnabled(),
                                  i18n.t("wb.detail_marker"), self.foregroundRole())

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._wciecie is not None:
            self._maluj_wskaznik(QPainter(self))

    def contextMenuEvent(self, event):
        zaznaczalne = bool(self.textInteractionFlags() & Qt.TextSelectableByMouse)
        if not (self._szczegol or self._polecenie or _LAMANIE in super().text()
                or (self._zdanie and not zaznaczalne)):
            super().contextMenuEvent(event)
            return
        if self._menu is not None:
            self._menu.deleteLater()
        self._menu = QMenu(self)
        # Treść ZAMROŻONA przy otwarciu menu: pole bywa przepisane, zanim ręka kliknie pozycję (raport
        # paska gaśnie, `setText("")`) - kopia ma oddać to, co człowiek widział przy prawym kliku.
        zaznaczenie, zdanie, szczegol = self.selectedText(), self._pelne, self._szczegol
        polecenie = self._polecenie
        schowek = QGuiApplication.clipboard()
        if zaznaczenie:
            self._menu.addAction(i18n.t("wb.copy_selection"), lambda: schowek.setText(zaznaczenie))
        self._menu.addAction(i18n.t("wb.copy_sentence"), lambda: schowek.setText(zdanie))
        if szczegol:
            self._menu.addAction(i18n.t("wb.copy_detail"), lambda: schowek.setText(szczegol))
        if polecenie:                    # samo polecenie - wklejone do terminala wykonuje się od razu
            self._menu.addAction(i18n.t("wb.copy_command"), lambda: schowek.setText(polecenie))
        self._menu.popup(event.globalPos())
        event.accept()


def _klucz_powodu(powod):
    """Tożsamość powodu do pytania „czy powody są różne” (AR-162): kod (`PowodPozycji.code`,
    `ZdanieRdzenia.code`), a bez kodu - tekst. Parametry kodu się nie liczą: „wiele obecnych kopii
    (2)” i „(3)” to ten sam powód."""
    kod = getattr(powod, "code", None)
    return ("kod", kod) if kod else ("tekst", str(powod))


def commit_do_cofniecia(res, czesc=None):
    """`commit_id`, który wolno cofnąć po operacji zapisu kart, albo None (C4/Z11, AR-359).

    Z FAKTAMI WYKONAWCY (`czesc` = `CzescZapisu` operacji - okna kart): decyduje zakres „Cofnij” z klas rdzenia
    (`CzescZapisu.zakres`, `writeback.zakresy_cofniecia` - te same fakty co szuflada Zbiorów): commit zakresu, gdy
    `zakres.cofnij` (podmiana potwierdzona albo niepotwierdzona - cofnięcie ją rozstrzyga), inaczej None - sam
    otwarty zapis w miejscu rozstrzyga odzysk („Przywróć nagłówek sprzed zapisu”), nie „Cofnij” (rdzeń odmówiłby
    `undo_open_op` w pętli bez wyjścia). Podmiana niepotwierdzona (`replace_unconfirmed`) „Cofnij” dostaje, choć
    `CommitResult.commit_id` jest None. Zakres NIEZNANY (odczyt faktów padł) - None: okno nie obiecuje cofnięcia, którego
    stanu nie zna (zdanie mówi to członem `wb.write_facts_unknown`). Okno kart pisze jednym kliknięciem jeden świeży
    przebieg, a jeden `writeback.commit` - najwyżej jeden commit, więc zakres ma jeden commit (EXPECT).

    BEZ FAKTÓW (`czesc` None - szuflada Zbiorów, która zakres liczy sama, wywołanie wprost): reguła rdzenia
    `CommitResult.commit_id` - nadany, gdy choć jeden plik został PODMIENIONY, także przy `failed` z `backup_text`
    (weryfikacja po podmianie padła, kopia nagłówka leży w `header_backups`); przebieg, w którym podmianę odbiła
    straż, `commit_id` nie dostaje (`writeback.commit`). Rename (`commit_renames`) `commit_id` nie nadaje - jego
    cofnięcie idzie po `run_id` i ma własną regułę w gridzie."""
    if czesc is None:
        return res.commit_id
    zakres = czesc.zakres
    if not czesc.zakres_znany or zakres is None or not zakres.cofnij:
        return None
    assert len(zakres.commity) == 1, zakres        # okno kart: jeden przebieg = jedna operacja = jeden commit
    return zakres.commity[0]


def spadek_na_droge_atomowa(fr):
    """Czy plik zapisano drogą atomową po odmowie zapisu w miejscu - po KODZIE rdzenia
    (`writeback.CODE_INPLACE_FALLBACK`), nie po zdaniu powodu."""
    return fr.code == writeback.CODE_INPLACE_FALLBACK


def bez_prefiksu_spadku(reason):
    """Powód spadku bez prefiksu rdzenia (`writeback.PREFIKS_DROGI_ATOMOWEJ`) - zdanie mówi już
    „drogą atomową”, drugi raz nie."""
    if reason.startswith(writeback.PREFIKS_DROGI_ATOMOWEJ):
        return reason[len(writeback.PREFIKS_DROGI_ATOMOWEJ):].lstrip(": ") or reason
    return reason


def _spadek_z_kodu(reason):
    """Czy powód to spadek z kodem i parametrami w kontrakcie (`detail` tekstem, uwagi krotką
    powodów) - wtedy dzieli się go po parametrach; inaczej (także zapis spoza kodeka) - prozą."""
    if not (isinstance(reason, PowodPozycji) and reason.code == "inplace_fallback"):
        return False
    p = dict(reason.params)
    return isinstance(p.get("detail"), str) and _uwagi_poprawne(p.get("notes", ()))


def podziel_powod_spadku(reason):
    """Powód pliku zapisanego drogą atomową → `(szczegół, uwaga | None)`. Rdzeń skleja go
    (`writeback._dopisz`, separator `; `) z prefiksu drogi, szczegółu odmowy zapisu w miejscu
    („operacja add/str na OBJECT…” - żargon, idzie do podpowiedzi) i uwag dopisanych za nim
    (kopia pliku sprzed podmiany zostawiona na dysku, nagrobek ręki - to są fakty dla człowieka
    i zostają w zdaniu). JEDEN podział dla trzech okien: „Zmień obiekt…”, „Napraw nagłówek…”,
    „Zatwierdź ze ścieżki…” (okna kart gubiły uwagę o kopii `*.horreum-kopia`).

    Powód z kodem spadku (`PowodPozycji` `inplace_fallback`, AR-141) dzieli się po PARAMETRACH, nie
    po prozie: szczegół = `detail`, uwagi = lista `notes` - oba w języku UI (`tekst_powodu`). Podział
    prozy zostaje dla powodu bez kodu (wiersz bazy sprzed 0041) i dla parametrów spoza kontraktu
    (`detail` nie-tekst, uwagi nie-lista powodów - zapis spoza kodeka; podział totalny)."""
    if _spadek_z_kodu(reason):
        p = dict(reason.params)
        uwagi = [tekst_powodu(n) for n in p.get("notes", ())]
        # Szczegół = powód odmowy zapisu w miejscu - z kodem (AR-148), więc też w języku UI.
        return tekst_powodu(p["detail"]), ("; ".join(uwagi) or None)
    szczegol, _, uwaga = bez_prefiksu_spadku(reason or "").partition("; ")
    return szczegol, (uwaga or None)


def _spadek_w_powodzie(powod):
    """Fragment spadku (`PowodPozycji` `inplace_fallback`) w drzewie powodu - sam powód, jego
    parametry i uwagi - albo None."""
    if not isinstance(powod, PowodPozycji):
        return None
    if powod.code == "inplace_fallback":
        return powod
    for _nazwa, wartosc in powod.params:
        for w in (wartosc if isinstance(wartosc, (list, tuple)) else (wartosc,)):
            znaleziony = _spadek_w_powodzie(w)
            if znaleziony is not None:
                return znaleziony
    return None


def _spadki(res):
    """`(FileResult, fragment spadku)` każdego pliku, który rdzeń przepisał drogą atomową po odmowie
    zapisu w miejscu - ORTOGONALNIE DO STATUSU (AR-161): `applied` (kod wyniku
    `CODE_INPLACE_FALLBACK`, powód zaczyna się od spadku), wstrzymany i 'failed' po dokonanej
    podmianie (uwaga drogi za powodem, `writeback._zapisz_lokacje`). 'blocked' - pliku nie
    przepisano, więc nie liczy się nigdy. Kolejność: zapisane, wstrzymane, błędy."""
    wynik = []
    for fr in res.applied + _wstrzymane_poza_zapisanymi(res) + res.failed:
        fragment = (fr.reason or None) if spadek_na_droge_atomowa(fr) \
            else _spadek_w_powodzie(fr.reason)
        if fragment is not None:
            wynik.append((fr, fragment))
    return wynik


def zdanie_drogi_zapisu(res):
    """Człon o SPADKU na drogę atomową przy zapisie w miejscu (AR-117) albo `""`.

    Okna kart i szuflada Zbiorów (AR-161) piszą w miejscu, bo pełne przepisanie pliku po SMB zrywa
    dowiązania `_WBPP`. Plik, w którym zapis w miejscu się nie kwalifikuje (np. FITS bez zapasu
    nagłówka na dopisaną kartę), rdzeń zapisuje drogą atomową i znaczy kodem
    (`spadek_na_droge_atomowa`) albo - gdy wynik ma inny status (wstrzymany, błąd po podmianie) -
    uwagą drogi w powodzie (`_spadki`). `applied` bez spadku to co innego (np. zapis potwierdzony
    z dysku po przerwanym commicie - nic nie przepisano). Droga zapisu jest szczegółem, dopóki
    wszystko poszło w miejscu, więc człon mówi wyłącznie o spadku: ile plików przepisano w całości
    i dlaczego - językiem człowieka (`wb.inplace_fallback`; szczegół rdzenia w podpowiedzi okna,
    `podpowiedz_spadku`) - oraz uwagi rdzenia dopisane za spadkiem (`podziel_powod_spadku`):
    liczba i pierwsza."""
    spadki = _spadki(res)
    if not spadki:
        return ""
    czlon = i18n.t("wb.inplace_fallback", n=len(spadki))
    uwagi = [u for u in (podziel_powod_spadku(fragment)[1] for _fr, fragment in spadki) if u]
    if uwagi:
        czlon += i18n.t("objchg.res.notes", n=len(uwagi), note=czytelny_powod(uwagi[0]))
    return czlon


# Ile plików przepisanych w całości podpowiedź wymienia z nazwy - reszta liczbą (`wb.fallback_more`).
_SPADKI_W_PODPOWIEDZI = 10


def podpowiedz_spadku(res):
    """Podpowiedź zdania wyniku okna piszącego karty (okna kart i szuflada Zbiorów): KAŻDY plik
    przepisany drogą atomową po odmowie zapisu w miejscu (każdy status, `_spadki`) wierszem „nazwa:
    szczegół rdzenia” w języku UI - najwyżej `_SPADKI_W_PODPOWIEDZI`, reszta liczbą - i na końcu
    wiersz o dowiązaniach (`wb.fallback_links`, AR-261): przepisany plik dostaje nowy węzeł, a jego
    dowiązanie twarde (wydanie `_WBPP`) zostaje przy starej treści. Zdanie warunkowe - liczby
    dowiązań przez SMB stwierdzić się nie da (udział podaje 1 także dla pliku z dowiązaniem). Zdanie
    główne mówi spadek liczbą (`zdanie_drogi_zapisu`); bez spadku `""`."""
    from horreum.gui.grid_model import _ogon_sciezki   # lazy: `grid_model` woła ten moduł leniwie
    spadki = _spadki(res)
    if not spadki:
        return ""
    # Szczegół z kodem jest już w języku UI (`podziel_powod_spadku` → `tekst_powodu`); proza bez kodu
    # (wiersz bazy sprzed 0041) przechodzi `czytelny_powod` - plik zajęty słowami okna, ścieżki bez `repr`.
    wiersze = [i18n.t("objchg.st.detail_tip",
                      detail=i18n.t("wb.reason_line", file=_ogon_sciezki(fr.path),
                                    reason=czytelny_powod(podziel_powod_spadku(fragment)[0])))
               for fr, fragment in spadki[:_SPADKI_W_PODPOWIEDZI]]
    if len(spadki) > _SPADKI_W_PODPOWIEDZI:
        wiersze.append(i18n.t_plural("wb.fallback_more", len(spadki) - _SPADKI_W_PODPOWIEDZI))
    wiersze.append(i18n.t("wb.fallback_links"))
    return "\n".join(wiersze)


def status_pozycji(stan, powod, kod=None, *, z_bazy=False):
    """`(status, podpowiedź)` wiersza listy okna zmiany obiektu: `stan` (tekst z katalogu) i powód
    rdzenia (`czytelny_powod`). SPADEK KARTY NA DROGĘ ATOMOWĄ mówi tym samym zdaniem człowieka, co
    wynik okna (`objchg.st.rewritten`, bliźniak `wb.inplace_fallback`), a nie żargonem rdzenia -
    szczegół schodzi do podpowiedzi, uwaga dopisana przez rdzeń za spadkiem zostaje w statusie
    (`podziel_powod_spadku`). Spadek rozpoznaje KOD - wyniku (`CODE_INPLACE_FALLBACK`, jak zdanie
    wyniku) albo powodu (`PowodPozycji` `inplace_fallback`, także z bazy po 0041, AR-141); wiersz
    z bazy bez kodu (`z_bazy`, sprzed 0041) rozpoznaje prefiks rdzenia (`PREFIKS_DROGI_ATOMOWEJ`).
    Każdy inny powód mówi zdaniem w języku UI (`tekst_powodu`). Błąd systemu w powodzie (AR-168)
    dokłada do podpowiedzi surowy tekst systemu (`szczegol_systemu`)."""
    if not powod:
        return stan, stan
    systemu = szczegol_powodu(powod)            # system i numer operacji z drogą wyjścia (AR-281)
    tip_systemu = "\n" + systemu if systemu else ""
    szczegol = None
    if (kod == writeback.CODE_INPLACE_FALLBACK or _spadek_z_kodu(powod)
            or (z_bazy and not _spadek_z_kodu(powod)
                and getattr(powod, "code", None) in (None, "inplace_fallback")
                and powod.startswith(writeback.PREFIKS_DROGI_ATOMOWEJ))):
        szczegol, uwaga = podziel_powod_spadku(powod)
        powod = i18n.t("objchg.st.rewritten") + (f"; {uwaga}" if uwaga else "")
    status = stan + i18n.t("objchg.st.reason", reason=tekst_powodu(powod))
    if szczegol is None:
        return status, status + tip_systemu
    return status, status + "\n" + i18n.t("objchg.st.detail_tip", detail=szczegol) + tip_systemu


# Plik zajęty przez inny program w powodzie rdzenia (`f"{type(exc).__name__}: {exc}"`):
# ERROR_SHARING_VIOLATION 32 i ERROR_LOCK_VIOLATION 33 - te same kody, przy których rdzeń ponawia
# przeniesienie i mówi „plik zajęty przez inny program” (AR-125). Komunikat systemu do KROPKI,
# którą go kończy (`ctypes.WinError`), albo do ścieżki (`str(OSError)` CPythona kropkę zdejmuje
# i dokleja `: 'ścieżka'`, przy przeniesieniu `'źródło' -> 'cel'`); nigdy dalej niż do członu
# zdania (`;`, ` · `, ` - `), więc dalsza część zdania („przerwano na żądanie”) zostaje.
_OS_ZAJETY = re.compile(
    r"\b\w*Error: \[WinError 3[23]\] (?:(?! · | - )[^.:;\n])*\.?"
    r"(?:: '(?P<sciezka>(?:[^'\\]|\\.)*)'(?: -> '(?:[^'\\]|\\.)*')?)?")
# Ścieżka w zapisie `repr` z podwojonymi ukośnikami (`'R:\\ASTRO_\\…'` z `str(OSError)`).
_REPR_SCIEZKI = re.compile(r"'((?:[^'\\]|\\.)*\\\\(?:[^'\\]|\\.)*)'")
# Surowy wyjątek systemu spoza klas rdzenia (`item_reasons.blad_systemu`: `f"{type(exc).__name__}: {exc}"`, AR-168,
# AR-388) - GRAMATYKA, nie podciąg: łańcuch nazw klas `[A-Z]…Error: ` (`ValueError: OSError: `) zaczęty na granicy
# członu zdania (początek tekstu albo po `: `, `; `, `(`, ` - `; łańcuch zaczęty poza granicą liczy się od drugiej
# klasy - każda następna stoi po `: `) i tuż za nim numer `[WinError N]`/`[Errno N]`. Tekst wyjątku do końca członu
# (`; `, ` · `, ` - `, `)`, koniec wiersza). Cytaty (`'…'`, `"…"` - ścieżka w zapisie `repr`, cytowana wartość albo
# treść innego wyjątku, nazwa pliku `'X:\L\OSError: [Errno 5].fits'`) wyłączone PRZED wyszukaniem, z zachowaniem
# pozycji. Jedno przejście: łańcuch klas dopasowany raz, w całości - koszt liniowy także dla „OSError: ” × tysiące.
_KLASA = re.compile(r"\b[A-Z]\w*?Error: ")
_LANCUCH_KLAS = re.compile(r"(?:\b[A-Z]\w*?Error: )+")
_NUMER_SYSTEMU = re.compile(r"\[(?P<numer>(?:WinError|Errno) \d+)\]")
_NUMERY_ZAJETOSCI = ("WinError 32", "WinError 33")     # zajętość - własne zdanie (`_OS_ZAJETY`), bez szczegółu
_GRANICE_CZLONU = (": ", "; ", "(", " - ")
_KONIEC_CZLONU = re.compile(r"; | · | - |\)|\n")
# Cytat w tekście powodu - ścieżka w zapisie `repr`, cytowana wartość albo treść (`'…'`, `"…"`).
_CYTAT = re.compile(r"'(?:[^'\\\n]|\\.)*'|\"(?:[^\"\\\n]|\\.)*\"")


def _surowe_wyjatki(tekst):
    """Surowe wyjątki systemu poza cytatem → `[(początek, koniec klas, koniec tekstu wyjątku, numer)]`, rosnąco:
    `tekst[początek:koniec klas]` - nazwy klas, które zdejmuje zdanie (`czytelny_powod`), `tekst[początek:koniec
    tekstu wyjątku]` - surowy tekst do szczegółu (`_surowy_systemu`), `numer` - `WinError N`/`Errno N`. Jedna
    gramatyka zdania i szczegółu; cytaty, łańcuchy klas i końce członów - po jednym przejściu."""
    maska = _CYTAT.sub(lambda m: "\0" * len(m.group(0)), tekst)     # wnętrze cytatu bez granic i klas, pozycje te same
    konce = [m.start() for m in _KONIEC_CZLONU.finditer(maska)]
    wynik, k = [], 0
    for m in _LANCUCH_KLAS.finditer(maska):
        numer = _NUMER_SYSTEMU.match(maska, m.end())
        if numer is None:
            continue
        poczatek = m.start()
        if poczatek and not maska.endswith(_GRANICE_CZLONU, 0, poczatek):
            poczatek = _KLASA.match(maska, poczatek).end()           # pierwsza klasa poza granicą członu
            if poczatek == m.end():
                continue
        while k < len(konce) and konce[k] < numer.end():
            k += 1
        wynik.append((poczatek, m.end(), konce[k] if k < len(konce) else len(tekst), numer.group("numer")))
    return wynik


def _bez_repr(sciezka):
    return sciezka.replace("\\\\", "\\")


def _bez_repr_sciezek(tekst):
    """Każda ścieżka z zapisu `repr` w tekście (`'R:\\\\ASTRO_\\\\…'`) bez podwojonych ukośników -
    jedna reguła dla zdania (`czytelny_powod`) i wiersza szczegółu systemu (`wiersz_szczegolu`)."""
    return _REPR_SCIEZKI.sub(lambda m: "'" + _bez_repr(m.group(1)) + "'", tekst)


def czytelny_powod(tekst):
    """Powód rdzenia w zdaniu dla człowieka: plik zajęty przez inny program słowami okna
    (`objchg.reason.busy`, bliźniak powodu przeniesienia rdzenia po AR-125) zamiast surowego
    `PermissionError: [WinError 32] …` - ścieżka zajętego pliku zostaje w nawiasie - a ścieżka
    z zapisu `repr` bez podwojonych ukośników. Reszta zdania znak w znak: powód rdzenia jest
    zdaniem dla człowieka, a przekład innych błędów systemu robi rdzeń (`item_reasons.blad_systemu`,
    AR-168, AR-184: odmowa dostępu, brak pliku, brak miejsca, udział - z kodem). Zajętość zostaje tutaj:
    rdzeń jej nie koduje, a wiersze bazy sprzed kodów są surowe. Jedna funkcja dla okien zapisu
    (zdanie wyniku `zdanie_wyniku_zapisu`, statusy okna zmiany obiektu).

    Wyjątek systemu spoza klas (`OSError: [WinError 87] …`, AR-388) mówi numer i komunikat systemu BEZ
    nazwy klasy Pythona (`_surowe_wyjatki`; tekst z klasą stoi w szczególe, `_surowy_systemu`) - rdzeń
    trzyma go znak w znak (AR-168), zdejmuje go dopiero zdanie: KAŻDY wyjątek tekstu w jednym przejściu, także
    wyjątek w komunikacie innego. Po zajętości (jej wzorzec niesie klasę). Idempotentna: wykonawca i okno
    przetwarzają to samo zdanie kolejno."""
    if not tekst:
        return tekst

    def _zajety(m):
        sciezka = m.group("sciezka")
        return i18n.t("objchg.reason.busy") + (f" ({_bez_repr(sciezka)})" if sciezka else "")

    tekst = _OS_ZAJETY.sub(_zajety, tekst)
    czesci, poz = [], 0
    for poczatek, klasy, _koniec, _numer in _surowe_wyjatki(tekst):
        czesci.append(tekst[poz:poczatek])
        poz = klasy
    return _bez_repr_sciezek("".join(czesci) + tekst[poz:])


def tekst_powodu(powod):
    """Powód rdzenia w języku UI (AR-141): `PowodPozycji` z wpisem `objchg.item.<kod>` → zdanie
    katalogu z parametrami (wpis mnogi odmienia parametr `n`); parametr-powód (`inner`, `outer`,
    fragmenty zdania) tą samą drogą, a proza warstwy bez kodu (pisarz karty, tekst systemu) znak
    w znak przez `czytelny_powod` - jawna granica. Uwagi (`notes`) idą za zdaniem po `; `, jak
    w rdzeniu. Powód bez kodu albo kod bez wpisu → `czytelny_powod` (dotychczasowe zdanie PL).
    W PL wynik = `czytelny_powod(zdanie rdzenia)` - test złoty i test AST katalogu.

    TOTALNE: powód, którego parametry nie pokrywają pól wpisu w języku UI (brak pola, zły typ, `n`
    wpisu mnogiego nie-liczbą, uwagi nie-lista powodów - zapis spoza kodeka), mówi zachowaną prozą
    rdzenia, nigdy wyjątkiem w oknie. Kompletność sprawdza raz `_zdanie_z_kodu`, nie łapanie błędu."""
    if isinstance(powod, PowodPozycji):
        zdanie = _zdanie_z_kodu(powod)
        if zdanie is not None:
            return zdanie
        return czytelny_powod(str(powod))
    return czytelny_powod(powod)


def zdanie_bledu_wzoru(exc):
    """Zdanie paska dla odmowy wzoru nazwy (`naming.validate_template`/`compose_name`, AR-193, AR-368): powód z kodem
    `rename_tpl_*` w języku UI (`tekst_powodu`), a tekst `re.error` Pythona złego wyrażenia (parametr `detail` kodu
    `rename_tpl_bad_regex`, język Pythona) - do szczegółu pod kursorem paska (`ZdanieZeSzczegolem`), nie do zdania PL.
    Jedno zdanie dla podglądu i stagingu nazw (`FramesView._zdanie_bledu_wzoru`)."""
    from horreum.item_reasons import powod_wyjatku
    powod = powod_wyjatku(exc)
    zdanie = i18n.t("grid.rename.error", e=tekst_powodu(powod))
    detail = (dict(powod.params).get("detail")
              if isinstance(powod, PowodPozycji) and powod.code == "rename_tpl_bad_regex" else None)
    if isinstance(detail, str) and detail:
        return ZdanieZeSzczegolem(zdanie, i18n.t("grid.token.regex_detail_tip", detail=detail))
    return zdanie


def _uwagi_poprawne(uwagi):
    return isinstance(uwagi, tuple) and all(isinstance(n, str) for n in uwagi)


def _zdanie_z_kodu(powod):
    """Zdanie wpisu `objchg.item.<kod>` w języku UI albo `None`, gdy wpisu nie ma albo parametry
    powodu go nie wypełniają: każde pole szablonu (każdej formy wpisu mnogiego) ma parametr, każdy
    parametr ma rodzaj z kontraktu (`item_reasons.PARAM_KINDS`: tekst albo liczba całkowita),
    uwagi to krotka powodów."""
    wpis = CATALOG.get(f"objchg.item.{powod.code}")
    if not isinstance(wpis, dict):
        return None
    forma = wpis.get(i18n.current_lang()) or wpis.get(i18n.DEFAULT)
    szablony = list(forma.values()) if isinstance(forma, dict) else [forma]
    p = dict(powod.params)
    uwagi = p.pop("notes", ())
    if not _uwagi_poprawne(uwagi) or not all(param_ok(k, v) for k, v in p.items()):
        return None
    pola = {f for s in szablony if isinstance(s, str)
            for _, f, _, _ in string.Formatter().parse(s) if f}
    if not pola <= set(p):
        return None
    # Parametr-lista (`features`, `paths`, AR-148): elementy w języku UI, złączone jak w rdzeniu.
    p = {k: (", ".join(tekst_powodu(x) for x in v) if isinstance(v, (list, tuple))
             else tekst_powodu(v) if isinstance(v, str) else v) for k, v in p.items()}
    if isinstance(forma, dict):
        n = p.pop("n", None)
        if not isinstance(n, int) or isinstance(n, bool):
            return None
        tekst = i18n.t_plural(f"objchg.item.{powod.code}", n, **p)
    else:
        tekst = i18n.t(f"objchg.item.{powod.code}", **p)
    return "; ".join([tekst, *(tekst_powodu(u) for u in uwagi)])


def zdanie_commitu_kart(res, applied_key, czesc=None, *, przycisk=None):
    """Zdanie commitu okna piszącego karty → `(tekst, commit_id do cofnięcia | None)`: zdanie
    wyniku + człon o spadku na drogę atomową (`zdanie_drogi_zapisu` - pusty, gdy wszystko poszło
    w miejscu) + nota przerwania + `commit_id` (po zamknięciu okna to jedyny uchwyt do cofnięcia).
    Okna kart piszą jedną operacją z szufladą (`commit`, zapis w miejscu ze spadkiem - AR-258), więc
    flaga drogi zniknęła: spadek rozpoznaje rdzeń po kodzie, a wynik zwykłego commitu atomowego
    spadku nie niesie.

    Z FAKTAMI WYKONAWCY (`czesc`, AR-359): „Cofnij” z zakresu (`commit_do_cofniecia(res, czesc)`), a zdanie mówi
    człony plików bez dowodu podmiany tą samą funkcją co szuflada (`czlony_niepewnych`: „do sprawdzenia -
    „{przycisk}” je sprawdzi”, „przerwany zapis w miejscu - najpierw „Przywróć nagłówek…””); `przycisk` = etykieta,
    którą zdanie nazywa uchwyt cofnięcia (przycisk okna, po zamknięciu - polecenie CLI). Zakres nieznany - człon
    `wb.write_facts_unknown`, a numer commitu rdzenia zostaje kotwicą (droga CLI), bez „Cofnij”.

    Okna kart nie mają listy pozycji: przy różnych powodach pozostałe stoją w podpowiedzi zdania
    (`podpowiedz_powodow`), a zdanie mówi, gdzie ich szukać (`wb.reasons_tip`)."""
    summary = zdanie_wyniku_zapisu(res, applied_key)
    if len(_rozne_powody(res)) > 1:
        summary += i18n.t("wb.reasons_tip")
    summary += zdanie_drogi_zapisu(res)
    if res.cancelled:
        summary += i18n.t("wb.cancelled_note")
    cofnij = commit_do_cofniecia(res, czesc)
    kotwica = cofnij
    if czesc is not None and not czesc.zakres_znany:
        summary += i18n.t("wb.write_facts_unknown")
        kotwica = res.commit_id
    elif czesc is not None and czesc.zakres is not None:
        assert przycisk, "człony plików bez dowodu podmiany nazywają uchwyt cofnięcia"
        summary += czlony_niepewnych(czesc.zakres.do_sprawdzenia, czesc.zakres.otwarte, przycisk=przycisk)
    if kotwica is not None:
        summary += i18n.t("grid.wb.commit_id", id=kotwica)
    return summary, cofnij


def zdanie_undo_kart(res):
    """Zdanie wyniku cofnięcia - wspólne dla okien piszących karty. Plik „już cofnięty”
    (`UndoResult.already`) to nie blokada, tylko stan docelowy: liczy się osobnym członem, inaczej
    dokończone ponowienie brzmiało jak porażka („1 przywrócony · 33 zablokowane”). Plik bez wersji
    z tego commitu (`UndoResult.not_replaced`, AR-388 - backup rozstrzygnięty z dyskiem bez dowodu
    podmiany) ma własny człon: „już cofnięte” mówiło o pliku, w którym wersji z tego commitu nie ma."""
    msg = _liczba("grid.wb.restored", len(res.restored))
    if res.semantic:
        msg += " · " + _liczba("grid.wb.semantic", len(res.semantic))
    if res.withheld:                                     # AR-82: nagłówek wrócił, zeznanie nie
        msg += " · " + _liczba("grid.wb.undo_withheld", len(res.withheld))
    bez_wersji = getattr(res, "not_replaced", ())       # wynik bez tej wiedzy (atrapa) - całe `already` „już cofnięte”
    juz = [fr for fr in res.already if fr not in bez_wersji]
    if juz:
        msg += " · " + _liczba("wb.undo_already", len(juz))
    if bez_wersji:
        msg += " · " + _liczba("wb.undo_not_replaced", len(bez_wersji))
    zablokowane = [fr for fr in res.blocked if fr not in res.already]
    if zablokowane:
        msg += " · " + _liczba("grid.wb.blocked", len(zablokowane))
    if res.failed:
        msg += " · " + _liczba("grid.wb.errors", len(res.failed))
    # AR-311: stan obiektu klatek z karty `OBJECT` po „Rozwiąż” - fakt RDZENIA (`UndoResult`), ta sama
    # liczba na każdej powierzchni cofnięcia; wynik bez tej wiedzy (atrapa, `undo_renames`) - bez członu.
    wrocily = getattr(res, "objects_restored", ())
    if wrocily:
        msg += " · " + _liczba("wb.undo_objects_restored", len(wrocily))
    zostaja = getattr(res, "objects_kept", ())
    if zostaja:
        msg += " · " + _liczba("wb.undo_objects_kept", len(zostaja))
    # AR-364: klatki przy obiekcie z nagłówka, którego cofnięta karta nie ma dowodu pochodzenia - zostają, zdanie mówi.
    bez_dowodu = getattr(res, "objects_unproven", ())
    if bez_dowodu:
        msg += " · " + _liczba("wb.undo_objects_unproven", len(bez_dowodu))
    return msg


def ogon_cofniecia(res, przycisk):
    """Ogon cofnięcia commitu kart → `(zdanie, czy „Cofnij” zostaje)` - JEDNA reguła dla trzech
    powierzchni (szuflada Zbiorów, „Napraw nagłówek…”, „Zatwierdź ze ścieżki…”, AR-160); `przycisk`
    = etykieta przycisku cofnięcia tej powierzchni, którą zdanie nazywa.

    Zdanie: liczniki (`zdanie_undo_kart`) + pierwszy powód z nazwą pliku - błędu przed blokadą,
    jak w `zdanie_wyniku_zapisu` - w języku UI (`tekst_powodu`). Okna kart mówiły same liczniki,
    więc kody powodów cofnięcia (AR-148) do nich nie docierały.

    „COFNIJ” ZNIKA WYŁĄCZNIE PRZY COFNIĘCIU DOMKNIĘTYM - fakt liczy RDZEŃ (`UndoResult.complete`
    z `_CofniecieLokacji.juz`), nie ten moduł ze statusów: każdy plik wrócił albo jest „już
    cofnięty”, pętla nie przerwana, nic nie padło. Inaczej uchwyt zostaje przy tym samym commicie:
      * `failed` - nagłówek przywrócony bez re-syncu („ponowne undo dokończy”), podmiana bez
        weryfikacji, operacja w miejscu przerwana; także błąd, którego ponowienie nie naprawi
        (uszkodzona koperta backupu) - uchwyt nie ginie, zdanie mówi powód;
      * `cancelled` - pętla `writeback.undo` przerywa PRZED kolejnymi backupami (także
        `restored` + `cancelled`); ponowienie sprawdzi pozostałe pliki;
      * `blocked` bez „już cofnięte” - nieudana rekoncyliacja backupu (`backup_reconcile_failed`
        wprost każe ponowić), izolacja cudzą operacją, plik zmieniony od commitu: plik NIE wrócił,
        więc „pliki są bez karty” byłoby fałszem, a zgaszony uchwyt - utratą jedynej drogi.
    Ponowienie jest bezpieczne: plik już cofnięty rdzeń odda jako 'blocked' „już cofnięte”.

    PRZERWANIE MÓWI PRAWDĘ RDZENIA, BEZ OBIETNICY (AR-176): `UndoResult.remaining` = ile
    nieprzetworzonych backupów nie ma trwałego dowodu zakończenia - „N nieprzetworzonych plików
    wymaga sprawdzenia; „Cofnij” ponowi próbę” albo, przy zerze, „pozostałe pliki nie wymagają
    cofnięcia”; wynik bez tej wiedzy (`None`, cofnięcie Nazw) - „„Cofnij” ponowi próbę dla
    pozostałych plików”. Uchwyt zostaje przy każdym przerwaniu: ponowienie rozstrzyga pliki.
    Gdy rdzeń zna pliki NIETKNIĘTE (`UndoResult.untouched` > 0, AR-318) - „N nietkniętych plików
    zostaje w stanie po zapisie, M wymaga sprawdzenia; „Cofnij” dokończy cofnięcie”."""
    from horreum.gui.grid_model import _ogon_sciezki   # lazy: `grid_model` woła ten moduł leniwie
    msg = zdanie_undo_kart(res)
    # Powód „już cofnięte” nie mówi niczego, co człon „N już cofniętych” nie powiedział (AR-160); powód pliku bez wersji
    # z tego commitu - to, co człon `wb.undo_not_replaced` (AR-388).
    detail = next((fr for fr in res.failed + res.blocked
                   if fr.reason and fr not in res.already), None)
    if detail is not None:
        msg += i18n.t("grid.inplace.detail", file=_ogon_sciezki(detail.path),
                      detail=tekst_powodu(detail.reason))
    if res.cancelled:
        reszta = getattr(res, "remaining", None)
        nietkniete = getattr(res, "untouched", None) or 0
        if reszta is None:
            msg += i18n.t("wb.undo_cancelled", undo=przycisk)
        elif nietkniete:
            # AR-318: rdzeń WIE, że te pliki są w stanie po zapisie - zdanie mówi to, a „wymaga
            # sprawdzenia” zostaje dla reszty bez tej wiedzy.
            msg += i18n.t_plural("wb.undo_cancelled_untouched", nietkniete)
            if reszta > nietkniete:
                msg += i18n.t_plural("wb.undo_cancelled_also_check", reszta - nietkniete)
            msg += i18n.t("wb.undo_cancelled_finish", undo=przycisk)
        elif reszta:
            msg += i18n.t_plural("wb.undo_cancelled_check", reszta, undo=przycisk)
        else:
            msg += i18n.t("wb.undo_cancelled_done")
    elif not res.complete:
        msg += i18n.t("grid.wb.undo_retry", undo=przycisk)
    return msg, not res.complete


# ------------------------------------------------ wynik CZĘŚCIOWY zapisu szuflady (AR-344)
# Anulowanie i awaria w środku zapisu mówią jednym ogonem (`ogon_czesci_zapisu`): co czeka na dokończenie
# albo co cofa „Cofnij”. Głowa awarii liczy pliki z FAKTÓW wykonawcy (`CzescZapisu` - baza, nie postęp:
# plik zapisany ze statusem `withheld`/`failed` po re-syncu albo zapisany przed wyjątkiem bez postępu też
# jest zapisany), więc szuflada nie mówi „Zatwierdzono: 3” obok „nie powiódł się”.


def ogon_czesci_zapisu(czeka, *, blad=False, cofnij=None, nazwy=False):
    """Ogon zdania zapisu przerwanego: anulowanie (`blad=False`) - „ - przerwano, N do dokończenia”
    (`grid.wb.interrupted`, znak w znak jak dotąd); awaria z czekającymi - „ - N do dokończenia”; awaria bez
    czekających przy żywym „Cofnij” (`cofnij` = etykieta przycisku) - co „Cofnij” cofa; inaczej `""`."""
    if not blad:
        return i18n.t("grid.wb.interrupted", n=czeka)
    if czeka:
        return i18n.t("grid.wb.partial_finish", n=czeka)
    if cofnij:
        return i18n.t("grid.wb.partial_undo_names" if nazwy else "grid.wb.partial_undo", undo=cofnij)
    return ""


def czlony_niepewnych(do_sprawdzenia, otwarte, *, przycisk):
    """Człony zdania o plikach bez dowodu podmiany (AR-345): „do sprawdzenia - „Cofnij” je sprawdzi”
    (podmiana niepotwierdzona, zwolnienie ręką - cofnięcie je rozstrzyga) i „przerwany zapis w miejscu -
    najpierw „Przywróć nagłówek…”” (operacja otwarta - cofnięcie odmawia `undo_open_op` i odsyła do odzysku)."""
    czlony = ""
    if do_sprawdzenia:
        czlony += i18n.t_plural("grid.wb.to_check", do_sprawdzenia, undo=przycisk)
    if otwarte:
        czlony += i18n.t_plural("grid.wb.open_write", otwarte, restore=i18n.t("grid.inplace.restore"),
                                nav=i18n.t("nav.porzadki"), row=i18n.t("tasks.torn_write_frames"))
    return czlony


def zdanie_czesci_zapisu(op, czesc, msg, *, czeka, cofnij, przycisk):
    """Zdanie awarii zapisu kart (`op` `commit`) albo nazw (`commit_rename`), który zdążył ruszyć pliki -
    „N z M zapisane, potem błąd: <powód>” + człony niepewnych + ogon (`ogon_czesci_zapisu`) - albo None,
    gdy fakty nie znają żadnego pliku tej operacji (wtedy mówi zdanie operacji `grid.wb.op.<op>`). N z bazy;
    odczyt faktów padł - „co najmniej N” z postępu. `msg` - powód w języku UI (szczegół idzie protokołem
    zdania i szczegółu wołającego)."""
    if czesc is None or czesc.wszystkie is None:
        return None
    pewne = czesc.zapisane is not None
    n = czesc.zapisane if pewne else len(czesc.applied)
    if n + czesc.do_sprawdzenia + czesc.otwarte == 0:
        return None
    nazwy = op == "commit_rename"
    klucz = ("grid.wb.partial_rename" if nazwy else "grid.wb.partial_commit") + ("" if pewne else "_min")
    return (i18n.t_plural(klucz, n, m=czesc.wszystkie, msg=msg)
            + czlony_niepewnych(czesc.do_sprawdzenia, czesc.otwarte, przycisk=przycisk)
            + ogon_czesci_zapisu(czeka, blad=True, cofnij=cofnij, nazwy=nazwy))


def zdanie_porazki_okna_kart(czesc, msg, *, przycisk):
    """Porażka zapisu kart OKNA („Napraw nagłówek…”, „Zatwierdź ze ścieżki…”), który zdążył ruszyć pliki (AR-384) →
    `(zdanie, commit do cofnięcia | None)`, albo None, gdy fakty wykonawcy nie znają żadnego pliku tej operacji (okno
    mówi wtedy samo „BŁĄD: …”). Wynik niepusty = zapis ruszył pliki: przycisk zapisu milczy jak po sukcesie.

    Te same fakty i ta sama głowa co szuflada (`zdanie_czesci_zapisu`: „N z M zapisane, potem błąd: …” + człony
    niepewnych), ale okno zdejmuje staging (`_porzuc_staging`), więc czekające się nie liczą (`czeka=0`) - przebiegu
    do dokończenia nie ma i „N do dokończenia” byłoby fałszem. „Cofnij” z zakresu rdzenia (`commit_do_cofniecia`
    z faktami, nie z wyniku, którego po wyjątku nie ma) z kotwicą commitu; fakty nieznane (odczyt klas padł,
    „co najmniej N” z postępu) - człon `wb.write_facts_unknown`, bez „Cofnij”. `przycisk` = etykieta uchwytu
    cofnięcia, którą zdanie nazywa (przycisk okna, po zamknięciu - polecenie CLI). `msg` - powód w języku UI."""
    if czesc is None:
        return None
    cofnij = commit_do_cofniecia(None, czesc)
    zdanie = zdanie_czesci_zapisu("commit", czesc, msg, czeka=0,
                                  cofnij=przycisk if cofnij is not None else None, przycisk=przycisk)
    if zdanie is None:
        return None
    if not czesc.zakres_znany:
        zdanie += i18n.t("wb.write_facts_unknown")
    if cofnij is not None:
        zdanie += i18n.t("grid.wb.commit_id", id=cofnij)
    return zdanie, cofnij
