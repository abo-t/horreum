"""Wspólny WYKONAWCA writebacku off-thread — worker + uchwyt startu/sprzątania dla KAŻDEJ
powierzchni, która commituje albo cofa zmiany plików (P-D/D-PD-3).

Do P-D mieszkał w `grid.py` i był prywatny dla „Zbiorów". Druga powierzchnia (dialog „Napraw
nagłówek…" osi obiektu) potrzebuje tego samego cyklu, a SKOPIOWANIE klasy powieliłoby naprawę
deadlocku AB-BA (GIL × `~QThread`, 2026-07-20), która raz już kosztowała sesję debugowania —
dlatego wędruje TU cały zestaw: worker, dyspozycja `_OPS`, fallback inline dla `:memory:`
i cleanup z `wait()`.

Warstwa widżetów (import Qt uprawniony), ale ŻADNEGO widżetu nie dotyka: postęp/koniec/błąd
wracają sygnałami, a wołający sam gasi przyciski i rysuje pasek — dlatego w `grid.py` zostaje
kilkulinijkowy launcher robiący WYŁĄCZNIE rzeczy widżetowe.

Uchwyt jest PER POWIERZCHNIA, nie singleton: wspólna instancja zlałaby `is_busy`, `cancel()`
i callbacki dwóch niezależnych operacji. Wzajemne wykluczenie DWÓCH powierzchni jest więc
osobnym faktem i mieszka w gospodarzu (`MainWindow`) — patrz `app.py`.
"""

from __future__ import annotations

import dataclasses
import re
import string
import threading

from PySide6.QtCore import QObject, QThread, Signal, Slot

from horreum import db, lead_copy, writeback
from horreum.gui import i18n
from horreum.item_reasons import PowodPozycji, param_ok   # powód pozycji z kodem (AR-141)
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


class WritebackWorker(QObject):
    """Wykonawca commitu/undo writebacku w wątku tła — bliźniak `PipelineWorker` (pipeline.py §4).
    Otwiera WŁASNE połączenie w SWOIM wątku (`db.connect`; sqlite `check_same_thread` — połączenia
    nie dzielimy między wątkami) i woła Qt-wolny rdzeń `writeback.*` z callbackami `progress`/
    `should_cancel`. NIE dotyka widżetów. Rdzeń commituje per-plik → anulowanie (`Event`) albo wyjątek
    zostawia czysty stan applied/pending (utrwalony). Połączenie zamykane PRZED emisją `done`, żeby
    slot głównego wątku czytał tylko przez `self.con` (bez nakładania połączeń na tym samym pliku)."""

    progress = Signal(int, int, str, str)   # done, total, path, status — MID-commit (Qt-wolny callback rdzenia)
    done = Signal(str, object)              # op, result (CommitResult|UndoResult|InplaceGestureResult|ObjectChangeResult) - niemutowany po zwrocie rdzenia
    failed = Signal(str, str)               # op, msg — wyjątek → sygnał, NIE crash apki
    finished = Signal()                     # run() wrócił KAŻDĄ drogą → quit wątku

    # Pętle po plikach dzielą sygnaturę (con, target_id, now=, progress=, should_cancel=); gest
    # kopii wiodącej bierze ją bez postępu i bez anulowania (jeden plik).
    # Trzy pętle za cofnięciem renamu to gesty izolacji zapisu w miejscu: cel = LISTA `inplace_op.id`, wynik
    # `InplaceGestureResult` (AR-17 (2) - ten sam uchwyt, więc ten sam mutex „writeback → Dostawa").
    # Zwolnienie ręką niesie też POWÓD człowieka, więc jego cel to `{"ops": [...], "reason": ...}`;
    # idzie tym uchwytem, bo rdzeń bierze blokadę pliku (`writeback.release_isolation`) i może na
    # nią czekać - w wątku okna byłoby to zamrożenie, a poza uchwytem - drugi pisarz obok zapisu.
    # Trzy wpisy fali zmiany obiektu (AR-17 krok 3, AR-117) - ta sama sygnatura pętli po plikach:
    # `commit_inplace` to karta zapisana W MIEJSCU (spadek na drogę atomową z powodem w
    # `FileResult.reason`), bo pełne przepisanie pliku po SMB zrywa dowiązania `_WBPP`; `object_change`
    # i `undo_object_change` to JEDNA operacja gestu (przeniesienie + karta + baza per pozycja), bo
    # dwa starty uchwytu zwalniałyby między sobą mutex „zapis → Dostawa". Cel wszystkich trzech:
    # `run_id` przebiegu ze stagingu.
    _OPS = {
        "commit":        lambda con, t, now, pr, sc: writeback.commit(con, t, now=now, progress=pr, should_cancel=sc),
        "commit_inplace": lambda con, t, now, pr, sc: writeback.commit(
            con, t, now=now, progress=pr, should_cancel=sc, inplace=True),
        "object_change": lambda con, t, now, pr, sc: writeback.commit_object_change(
            con, t, now=now, progress=pr, should_cancel=sc),
        "undo_object_change": lambda con, t, now, pr, sc: writeback.undo_object_change(
            con, t, now=now, progress=pr, should_cancel=sc),
        "commit_rename": lambda con, t, now, pr, sc: writeback.commit_renames(con, t, now=now, progress=pr, should_cancel=sc),
        "undo":          lambda con, t, now, pr, sc: writeback.undo(con, t, now=now, progress=pr, should_cancel=sc),
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

    def __init__(self, db_path, op, target_id, *, now_fn):
        super().__init__()
        self._db_path = db_path
        self._op = op
        self._target_id = target_id
        self._now = now_fn
        self._cancel = threading.Event()

    def request_cancel(self):
        """Kooperatywne anulowanie — stawiane w GŁÓWNYM wątku, czytane w workerze (`Event` bezpieczny
        międzywątkowo; rdzeń sprawdza PRZED każdym plikiem, zostawiając zapisane 'applied')."""
        self._cancel.set()

    @Slot()
    def run(self):
        con = None
        result = None
        error = None
        try:
            con = db.connect(self._db_path)     # WŁASNE połączenie w TYM wątku (baza już zmigrowana)
            result = self._OPS[self._op](con, self._target_id, self._now(),
                                         self._emit_progress, self._cancel.is_set)
        except Exception as exc:                # błąd → sygnał, NIE crash
            error = f"{type(exc).__name__}: {exc}"
        finally:
            if con is not None:
                con.close()                     # zamknij PRZED done — main czyta tylko przez self.con
        if error is not None:
            self.failed.emit(self._op, error)
        else:
            self.done.emit(self._op, result)
        self.finished.emit()                    # zawsze: zwolnij wątek

    def _emit_progress(self, done, total, path, status):
        # wołane SYNCHRONICZNIE w wątku workera przez rdzeń; ~7 plików/s (I/O NAS) → emisja per plik tania
        self.progress.emit(done, total, path, status)


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

    def start(self, op, target_id, *, on_progress, on_done, on_failed) -> bool:
        """Odpal `op` (klucz `WritebackWorker._OPS`) na `target_id`. Zwraca False, gdy
        operacja już trwa (wołający nie ma wtedy prawa liczyć na callbacki). Sloty dostaje wołający
        — TEN moduł nie wie, co jest paskiem, a co przyciskiem."""
        if self._thread is not None:
            return False
        self._worker = WritebackWorker(self._db_path, op, target_id, now_fn=self._now)
        self._worker.progress.connect(on_progress)
        self._worker.done.connect(on_done)
        self._worker.failed.connect(on_failed)
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

    def refuse_close(self, say):
        """Straż zamknięcia OKNA-WŁAŚCICIELA tego uchwytu: `True` = operacja trwa, okno ma ZOSTAĆ.

        Uchwyt i jego `QThread` są dziećmi okna, więc zamknięcie okna w biegu niszczyłoby wątek,
        który jeszcze pracuje („QThread: Destroyed while thread is still running" = twardy abort).
        Wzorzec `projection_dialog.done` (wydanie w biegu): zamknięcie = ŻĄDANIE ANULOWANIA, okno
        zostaje - czekanie z timeoutem byłoby zakładem o czas jednego pliku po SMB, a raport
        przerwanego zapisu (ile plików zmieniono, `commit_id` do cofnięcia) musi mieć dokąd trafić.
        Drugie zamknięcie, już po biegu, zamyka. `say(tekst)` = gdzie okno mówi, co się dzieje.
        Jeden kod dla każdego okna z tym uchwytem (SPOT) - nie kopia warunku w każdym `done`."""
        if self._thread is None:
            return False
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
    zapisany: ponowienie albo cofnięcie przebiegu dokończy przepięcie"). Przy odwrotnej kolejności jedna blokada w tym samym wsadzie chowała go za sobą."""
    parts = [_liczba(noun_key, len(res.applied))]
    # AR-82: plik ZAPISANY, a zeznanie klatki go nie przyjęło - osobny człon, nie „0 zapisanych”.
    # Przy cofnięciu gestu `withheld` jest podzbiorem `applied` (karta wróciła) - tamto zdanie mówi
    # o nim własnym członem (`zdanie_wyniku_zmiany`), tu liczą się tylko pliki spoza `applied`.
    wstrzymane = [fr for fr in res.withheld if fr not in res.applied]
    if wstrzymane:
        parts.append(_liczba("grid.wb.withheld", len(wstrzymane)))
    if res.blocked:
        parts.append(_liczba("grid.wb.blocked", len(res.blocked)))
    if res.failed:
        parts.append(_liczba("grid.wb.errors", len(res.failed)))
    if res.skipped:
        parts.append(_liczba("grid.wb.skipped", len(res.skipped)))
    summary = " · ".join(parts)
    detail = next((fr.reason for fr in (res.failed + wstrzymane + res.blocked) if fr.reason), None)
    if detail:
        summary += i18n.t("grid.wb.detail_sep", detail=tekst_powodu(detail))
    return summary


def commit_do_cofniecia(res):
    """`commit_id`, który wolno cofnąć, albo None - JEDNA reguła dla wszystkich powierzchni (C4/Z11).

    Rdzeń nadaje `commit_id`, gdy choć jeden plik został PODMIENIONY - także przy `failed`
    z `backup_text` (weryfikacja po podmianie padła, plik jest zmieniony, kopia nagłówka leży
    w `header_backups`). Dawny warunek „`applied` niepuste" zostawiał taki plik zmieniony bez
    przycisku cofnięcia. Przebieg, w którym backup powstał, a podmianę odbiła straż (wiersz
    commitu jest w bazie), `commit_id` NIE dostaje - „Cofnij" commitu, który niczego nie zmienił,
    byłoby kłamstwem (`writeback.commit`). Rename (`commit_renames`) `commit_id` nie nadaje - jego
    cofnięcie idzie po `run_id` i ma własną regułę w gridzie."""
    return res.commit_id


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
    po prozie: szczegół = `detail`, uwagi = lista `notes` w języku UI (`tekst_powodu`). Podział
    prozy zostaje dla powodu bez kodu (wiersz bazy sprzed 0041) i dla parametrów spoza kontraktu
    (`detail` nie-tekst, uwagi nie-lista powodów - zapis spoza kodeka; podział totalny)."""
    if _spadek_z_kodu(reason):
        p = dict(reason.params)
        uwagi = [tekst_powodu(n) for n in p.get("notes", ())]
        return p["detail"], ("; ".join(uwagi) or None)
    szczegol, _, uwaga = bez_prefiksu_spadku(reason or "").partition("; ")
    return szczegol, (uwaga or None)


def zdanie_drogi_zapisu(res):
    """Człon o SPADKU na drogę atomową przy zapisie w miejscu (AR-117) albo `""`.

    Okna kart piszą w miejscu (`commit_inplace`), bo pełne przepisanie pliku po SMB zrywa
    dowiązania `_WBPP`. Plik, w którym zapis w miejscu się nie kwalifikuje (FITS umie w miejscu
    wyłącznie podmienić istniejącą kartę), rdzeń zapisuje drogą atomową i znaczy kodem
    (`spadek_na_droge_atomowa`). `applied` bez tego kodu to co innego (np. zapis potwierdzony
    z dysku po przerwanym commicie - nic nie przepisano). Droga zapisu jest szczegółem, dopóki
    wszystko poszło w miejscu, więc człon mówi wyłącznie o spadku: ile plików przepisano w całości
    i dlaczego - językiem człowieka (`wb.inplace_fallback`; szczegół rdzenia w podpowiedzi okna,
    `podpowiedz_spadku`) - oraz uwagi rdzenia dopisane za spadkiem (`podziel_powod_spadku`):
    liczba i pierwsza."""
    spadek = [fr for fr in res.applied if spadek_na_droge_atomowa(fr)]
    if not spadek:
        return ""
    czlon = i18n.t("wb.inplace_fallback", n=len(spadek))
    uwagi = [u for u in (podziel_powod_spadku(fr.reason)[1] for fr in spadek) if u]
    if uwagi:
        czlon += i18n.t("objchg.res.notes", n=len(uwagi), note=czytelny_powod(uwagi[0]))
    return czlon


def podpowiedz_spadku(res):
    """Podpowiedź zdania wyniku okna piszącego karty: szczegół rdzenia pierwszego spadku na drogę
    atomową - zdanie mówi go językiem człowieka (`zdanie_drogi_zapisu`), więc szczegół nie ginie,
    tylko schodzi pod kursor - albo `""`."""
    spadek = next((fr for fr in res.applied if spadek_na_droge_atomowa(fr) and fr.reason), None)
    if spadek is None:
        return ""
    return i18n.t("objchg.st.detail_tip", detail=podziel_powod_spadku(spadek.reason)[0])


def status_pozycji(stan, powod, kod=None, *, z_bazy=False):
    """`(status, podpowiedź)` wiersza listy okna zmiany obiektu: `stan` (tekst z katalogu) i powód
    rdzenia (`czytelny_powod`). SPADEK KARTY NA DROGĘ ATOMOWĄ mówi tym samym zdaniem człowieka, co
    wynik okna (`objchg.st.rewritten`, bliźniak `wb.inplace_fallback`), a nie żargonem rdzenia -
    szczegół schodzi do podpowiedzi, uwaga dopisana przez rdzeń za spadkiem zostaje w statusie
    (`podziel_powod_spadku`). Spadek rozpoznaje KOD - wyniku (`CODE_INPLACE_FALLBACK`, jak zdanie
    wyniku) albo powodu (`PowodPozycji` `inplace_fallback`, także z bazy po 0041, AR-141); wiersz
    z bazy bez kodu (`z_bazy`, sprzed 0041) rozpoznaje prefiks rdzenia (`PREFIKS_DROGI_ATOMOWEJ`).
    Każdy inny powód mówi zdaniem w języku UI (`tekst_powodu`)."""
    if not powod:
        return stan, stan
    szczegol = None
    if (kod == writeback.CODE_INPLACE_FALLBACK or _spadek_z_kodu(powod)
            or (z_bazy and not _spadek_z_kodu(powod)
                and getattr(powod, "code", None) in (None, "inplace_fallback")
                and powod.startswith(writeback.PREFIKS_DROGI_ATOMOWEJ))):
        szczegol, uwaga = podziel_powod_spadku(powod)
        powod = i18n.t("objchg.st.rewritten") + (f"; {uwaga}" if uwaga else "")
    status = stan + i18n.t("objchg.st.reason", reason=tekst_powodu(powod))
    if szczegol is None:
        return status, status
    return status, status + "\n" + i18n.t("objchg.st.detail_tip", detail=szczegol)


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


def _bez_repr(sciezka):
    return sciezka.replace("\\\\", "\\")


def czytelny_powod(tekst):
    """Powód rdzenia w zdaniu dla człowieka: plik zajęty przez inny program słowami okna
    (`objchg.reason.busy`, bliźniak powodu przeniesienia rdzenia po AR-125) zamiast surowego
    `PermissionError: [WinError 32] …` - ścieżka zajętego pliku zostaje w nawiasie - a ścieżka
    z zapisu `repr` bez podwojonych ukośników. Reszta zdania znak w znak: powód rdzenia jest
    zdaniem dla człowieka, a przekład innych błędów systemu to robota rdzenia, nie ekranu. Jedna
    funkcja dla okien zapisu (zdanie wyniku `zdanie_wyniku_zapisu`, statusy okna zmiany obiektu)."""
    if not tekst:
        return tekst

    def _zajety(m):
        sciezka = m.group("sciezka")
        return i18n.t("objchg.reason.busy") + (f" ({_bez_repr(sciezka)})" if sciezka else "")

    tekst = _OS_ZAJETY.sub(_zajety, tekst)
    return _REPR_SCIEZKI.sub(lambda m: "'" + _bez_repr(m.group(1)) + "'", tekst)


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
    p = {k: tekst_powodu(v) if isinstance(v, str) else v for k, v in p.items()}
    if isinstance(forma, dict):
        n = p.pop("n", None)
        if not isinstance(n, int) or isinstance(n, bool):
            return None
        tekst = i18n.t_plural(f"objchg.item.{powod.code}", n, **p)
    else:
        tekst = i18n.t(f"objchg.item.{powod.code}", **p)
    return "; ".join([tekst, *(tekst_powodu(u) for u in uwagi)])


def zdanie_commitu_kart(res, applied_key, *, w_miejscu=False):
    """Zdanie commitu okna piszącego karty → `(tekst, commit_id do cofnięcia | None)`: zdanie
    wyniku + nota przerwania + `commit_id` (po zamknięciu okna to jedyny uchwyt do cofnięcia).
    `w_miejscu` = commit szedł zapisem w miejscu (`commit_inplace`) - zdanie dokłada wtedy człon
    o spadku na drogę atomową (`zdanie_drogi_zapisu`); przy zwykłym commicie drogą atomową jest
    każdy plik i taki człon byłby fałszem."""
    summary = zdanie_wyniku_zapisu(res, applied_key)
    if w_miejscu:
        summary += zdanie_drogi_zapisu(res)
    if res.cancelled:
        summary += i18n.t("wb.cancelled_note")
    cofnij = commit_do_cofniecia(res)
    if cofnij is not None:
        summary += i18n.t("grid.wb.commit_id", id=cofnij)
    return summary, cofnij


def zdanie_undo_kart(res):
    """Zdanie wyniku cofnięcia - wspólne dla okien piszących karty."""
    msg = _liczba("grid.wb.restored", len(res.restored))
    if res.semantic:
        msg += " · " + _liczba("grid.wb.semantic", len(res.semantic))
    if res.withheld:                                     # AR-82: nagłówek wrócił, zeznanie nie
        msg += " · " + _liczba("grid.wb.undo_withheld", len(res.withheld))
    if res.blocked:
        msg += " · " + _liczba("grid.wb.blocked", len(res.blocked))
    if res.failed:
        msg += " · " + _liczba("grid.wb.errors", len(res.failed))
    return msg
