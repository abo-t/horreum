"""Horreum — menedżer biblioteki astrofoto deep-sky.

Baza = autorytet, pliki = append-only zimny magazyn, sha1 = tożsamość.
Zapis domenowy WYŁĄCZNIE przez `horreum.repo` (jedna klinga → event); pilnuje tego
statyczny meta-tripwir AST (`tests/test_repo_safety.py`) od commitu zero.

WERSJA MA JEDNEGO WŁAŚCICIELA: `pyproject.toml`. Literał, który stał tu wcześniej, przespał dwa
wydania — kod mówił `0.3.2`, gdy tag, wheel i opublikowany `.exe` mówiły `0.4.0`, więc
`horreum --version` (JEDYNA droga, którą użytkownik sprawdza, co ma) kłamał. Odtąd numer jest
CZYTANY: metadane zainstalowanej paczki (wheel, editable, frozen — specy wnoszą je przez
`copy_metadata`), a w gołym klonie bez instalacji wprost z `pyproject.toml`. Nieznanego numeru
NIE zgadujemy — oddajemy `"nieznana"`. Bramka klasy: `tests/test_version.py`.

Rozwiązanie jest LENIWE (PEP 562): płaci dopiero ten, kto pyta o wersję. Zmierzone 2026-10-24
(`.venv-build`, Python 3.13, Windows 11, 10 świeżych procesów, `perf_counter`): pierwsze sięgnięcie
w świeżym procesie 65-78 ms (mediana ~70 ms; z tego ~41 ms to sam import `importlib.metadata`), czyli
więcej niż cały import `horreum.cli` (53-61 ms); gdy `importlib.metadata` jest już w procesie (GUI -
ciągnie go import `horreum.gui.app`) - 20-24 ms. Każde kolejne sięgnięcie ~0,4 ms: wynik NIE jest
pamiętany, każde czyta metadane od nowa.
"""

def _read_version():
    """Numer z jedynego właściciela: metadane paczki → `pyproject.toml` obok pakietu → `nieznana`."""
    from importlib.metadata import PackageNotFoundError, version
    try:
        return version("horreum")
    except PackageNotFoundError:
        pass
    import re
    from pathlib import Path
    try:
        text = (Path(__file__).resolve().parent.parent / "pyproject.toml").read_text(encoding="utf-8")
    except OSError:
        return "nieznana"
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else "nieznana"


def __getattr__(name):
    """PEP 562 — `horreum.__version__` liczy się przy PIERWSZYM sięgnięciu (patrz nagłówek)."""
    if name == "__version__":
        return _read_version()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
