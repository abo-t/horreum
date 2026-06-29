"""Qt-WOLNA logika progresu skanu (PLAN_gui_pipeline §4/§5) — przerzedzanie emisji i migawka
liczników. Worker woła to w wątku tła; samą emisję sygnału Qt robi warstwa widżetów (`pipeline.py`).
Wydzielone, by testować bez PySide6 (skill `test-isolation-optional-dependencies`).

Ten plik MUSI zostać Qt-free (test izolacji `test_gui_isolation.py` pilnuje, że tylko `app.py`/
`__main__.py`/`pipeline.py` tykają PySide6)."""
from dataclasses import asdict


def should_emit(done, total, *, every=50):
    """Czy wyemitować sygnał progresu dla `done`/`total`. Skan to ~15 tys. plików — emisja per plik
    zalałaby pętlę zdarzeń. Emituj na PIERWSZYM (pasek rusza), OSTATNIM (domyka się na 100%) i co
    `every` plików. `total<=0` (puste drzewo) → nigdy (i tak nie ma czego pokazać)."""
    if total <= 0:
        return False
    return done == 1 or done == total or done % every == 0


def counts_snapshot(summary):
    """Migawka liczników jako DICT (`dataclasses.asdict`). Przez granicę wątku idzie KOPIA, nigdy
    żywy mutowalny `ScanSummary` — worker mutuje go dalej w pętli, więc przekazanie referencji =
    race (slot w głównym wątku czytałby pola w trakcie ich zmiany)."""
    return asdict(summary)
