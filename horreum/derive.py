"""Łańcuch etapów pochodnych - JEDEN właściciel kolejności (AR-39). Rdzeń Qt-wolny: woła go
wątek tła GUI (`PipelineWorker`), CLI (`presence --apply`) i import z dawcy (`import_fitsmirror`).

KOLEJNOŚĆ NIE JEST GUSTEM: `group` → `resolve` → `calibrate` → `lineage` → `stack_lineage`. Przepis flata bierze
`frame.filter_canon`, który wypełnia dopiero `run_resolver`, więc kalibracja przed resolverem
wyłoniłaby przepisy z pustym filtrem; rodowód dopasowuje light do profili, które `calibrate`
dopiero wyłania. Dopóki ta lista żyła w czterech kopiach, GUI, CLI i import dawały tę samą bazę
po tym samym geście tylko tak długo, jak kopie się nie rozjechały.

RODOWÓD STOSÓW (`stack_lineage`) ZAMYKA ŁAŃCUCH (AR-85): dobór okna stoi na osi obiektu i osi
teleskopu (`group`, `resolve`), więc Dostawa, która je zmieni, zostawiała rodowód stosów - z jego
werdyktem `integration.unresolved_reason` - zamrożony do ręcznego przeliczenia. Etap czyta nagłówki
XISF stosów z dysku (historia PixInsighta nie leży w bazie); zmierzone 2026-10-07 na kopii pf4:
193 stosy, 86,7 MB nagłówków, 3,6 s przebiegu bez zmian, drugi przebieg zero zdarzeń zapisu.

Przed pochodnymi stoją fakty kopii i przejęcie zeznania ocalałej kopii (`adopt_stages`): każdy
etap od `group` czyta `header`, a przejęcie zmienia `header`, więc pochodne policzone przed nim
mówiłyby głosem nieobecnego pliku do następnej dostawy. Fakty idą PRZED przejęciem - bez nich
predykat zeznania milczy („nie wiem") i przejęcie nie ma kandydata.

Funkcje zwracają GENERATOR par `(etap, wynik)`: wołający dostaje wynik zaraz po etapie, więc
GUI emituje sygnał po elemencie, a CLI drukuje wiersz, zanim ruszy następny etap - wyjątek
późniejszego etapu nie połyka raportu etapów już zapisanych. `list(...)` daje całą listę.
Etap bez kandydatów milczy całkowicie (QUIET): ani `on_start`, ani pary. Anulowany etap
oddaje swoją parę (wynik z `cancelled=True`) i kończy generator - dalsze etapy nie ruszają.

`now` to znacznik ISO albo funkcja bez argumentów, która go zwraca: GUI podaje swoją `now_fn`,
więc każdy etap długiego łańcucha dostaje świeży znacznik (jak wcześniej `_bulk`)."""
from . import calibration, grouper, lineage, resolver, scan, stacks

# Funkcje rdzenia wołane przez moduł (`grouper.run_grouper`), nie przez nazwę zaimportowaną:
# podmiana etapu w teście trafia wtedy we wszystkie drogi naraz, a sygnatury (`now`
# pozycyjnie albo nazwane) wyrównuje jedno miejsce.
# `should_cancel` dostaje tylko etap, który czyta pliki (rodowód stosów) - pozostałe liczą
# z bazy w sekundach, a anulowanie między etapami trzyma `_emit_chain`.
DERIVED_STAGES = (
    ("group", lambda con, now, should_cancel=None: grouper.run_grouper(con, now)),
    ("resolve", lambda con, now, should_cancel=None: resolver.run_resolver(con, now)),
    ("calibrate", lambda con, now, should_cancel=None: calibration.run_calibration(con, now=now)),
    ("lineage", lambda con, now, should_cancel=None: lineage.run_lineage(con, now=now)),
    ("stack_lineage", lambda con, now, should_cancel=None: stacks.run_stack_lineage(
        con, now=now, should_cancel=should_cancel)),
)
DERIVED = dict(DERIVED_STAGES)


def _zegar(now):
    return now if callable(now) else (lambda: now)


def run_derived(con, now, *, on_start=None, should_cancel=None):
    """Same pochodne w kolejności `DERIVED_STAGES` - bez faktów kopii i przejęcia (import ze
    świeżej bazy nie ma kopii do uzupełnienia). Generator `(etap, wynik)`; etap anulowany
    (`wynik.cancelled`) kończy go."""
    zegar = _zegar(now)
    for name, fn in DERIVED_STAGES:
        if on_start is not None:
            on_start(name)
        wynik = fn(con, zegar(), should_cancel)
        yield name, wynik
        if getattr(wynik, "cancelled", False):
            return


def adopt_stages(con, root, now, should_cancel=None, *, on_start=None, progress=None):
    """Fakty kopii → przejęcie zeznania, oba zawężone do `root` (`None` = całe archiwum).
    `progress(etap, done, total, path, summary)` - postęp per plik obu etapów. Generator
    `(etap, wynik)`; anulowanie kończy go na anulowanym etapie.

    FAKTY KOPII (0021) w Dostawie, nie osobnym przyciskiem ani CLI: wydanie jedzie jako sam GUI,
    a kopie sprzed migracji skan z bramą przyrostową pomija (mtime bez zmian), więc bez tego
    etapu żywa baza nie dostałaby faktów kopii nigdy. Sterownik czyta SAME nagłówki, a po
    pierwszym przebiegu jego SELECT jest pusty - wtedy etap milczy.

    PRZEJĘCIE ZEZNANIA (AR-5) sterowane stanem (`scan.adopt_candidates`): klatki, których
    `header` pochodzi z kopii już nieobecnej, a jedyna obecna kopia mówi co innego. Klatki
    o dwóch i więcej obecnych kopiach albo z zeznaniem ręki zostają człowiekowi (AR-4).

    ZAKRES = korzeń przebiegu (jak pass obecności). Każda kopia i każda klatka to osobna
    transakcja, więc anulowanie zostawia bazę spójną, a następna dostawa dobierze resztę."""
    zegar = _zegar(now)
    if scan.copy_facts_candidates(con, root):
        if on_start is not None:
            on_start("copy_facts")
        f = scan.backfill_copy_facts(con, now=zegar(), root=root,
                                     progress=_etap(progress, "copy_facts"),
                                     should_cancel=should_cancel)
        yield "copy_facts", f
        if f.cancelled:
            return
    if scan.adopt_candidates(con, root):
        if on_start is not None:
            on_start("adopt_testimony")
        yield "adopt_testimony", scan.adopt_orphan_testimony(
            con, now=zegar(), root=root, progress=_etap(progress, "adopt_testimony"),
            should_cancel=should_cancel)


def adopt_and_derive(con, root, now, should_cancel=None, *, derive_always=False, on_start=None,
                     progress=None):
    """`adopt_stages`, potem `run_derived`. Generator `(etap, wynik)`.

    Pochodne ruszają wyłącznie po REALNYM przejęciu (gesty bez skanu: ogon „Oznacz zniknięte",
    „Zbierz fakty kopii", CLI `presence --apply`) - bez niego zeznania nic nie ruszyło, więc
    przeliczanie archiwum byłoby kosztem bez skutku. `derive_always=True` - Dostawa po skanie:
    skan sam zmienia bazę, więc pochodne idą zawsze, o ile nic nie anulowano."""
    przejete = 0
    for name, wynik in adopt_stages(con, root, now, should_cancel, on_start=on_start,
                                    progress=progress):
        yield name, wynik
        if wynik.cancelled:
            return
        if name == "adopt_testimony":
            przejete = wynik.adopted
    if derive_always or przejete:
        yield from run_derived(con, now, on_start=on_start, should_cancel=should_cancel)


def _etap(progress, name):
    if progress is None:
        return None
    return lambda done, total, path, s: progress(name, done, total, path, s)
