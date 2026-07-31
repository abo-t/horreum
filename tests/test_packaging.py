"""META-TRIPWIR (statyczny) — assety pakietu wchodzą do KAŻDEJ drogi dystrybucji.

Horreum jedzie do użytkownika dwiema drogami: wheel (`pip install .`) i frozen `.exe` (PyInstaller).
Kod dowozi obie, ale pliki DANYCH (migracje `.sql`, katalog celów, uniwersalia, mapa lądów) każda
droga bierze osobnym mechanizmem — i to tam powstaje dziura: asset dopisany do speca, ale nie do
`package-data`, jest niewidoczny dopóki ktoś nie zainstaluje pakietu naprawdę (frozen działa,
`pip install -e .` też, bo editable czyta drzewo źródeł). Ten plik pilnuje OBU stron naraz.

Nie sprawdza, czy konkretny katalog jest wymieniony — sprawdza, czy KAŻDY realny plik danych
w `horreum/` jest pokryty. Dzięki temu nowy katalog assetów nie wymaga dopisania testu."""
import fnmatch
from pathlib import Path

import pytest

import horreum

try:
    import tomllib
except ImportError:                                   # <3.11 — bramka jest dev-only, nie runtime
    tomllib = None

PKG = Path(horreum.__file__).parent
ROOT = PKG.parent
RESOURCE_SUFFIXES = (".json", ".sql")                 # rozszerzenia czytane w runtime
SPECS = ("packaging/horreum.spec", "packaging/horreum-onefile.spec")


def _resources():
    """Pliki danych pakietu jako pary (nazwa paczki, nazwa pliku) — `__pycache__` poza."""
    out = []
    for p in sorted(PKG.rglob("*")):
        if (p.is_file() and p.suffix in RESOURCE_SUFFIXES
                and "__pycache__" not in p.parts):
            parts = p.parent.relative_to(PKG).parts
            out.append((".".join(("horreum",) + parts), p.name))
    return out


def _pyproject():
    if tomllib is None:
        pytest.skip("tomllib wymaga Pythona 3.11+")
    with open(ROOT / "pyproject.toml", "rb") as fh:
        return tomllib.load(fh)["tool"]["setuptools"]


def test_kazdy_asset_pakietu_jest_pokryty_przez_package_data():
    """Bez wpisu w `package-data` plik NIE wchodzi do wheela — a brak widać dopiero na czystej
    instalacji, nigdy w dev (editable czyta drzewo źródeł)."""
    package_data = _pyproject()["package-data"]
    resources = _resources()
    assert resources, "brak plików danych w pakiecie — test straciłby przedmiot"
    for package, filename in resources:
        covered = any(fnmatch.fnmatch(package, key) and fnmatch.fnmatch(filename, pattern)
                      for key, patterns in package_data.items() for pattern in patterns)
        assert covered, (
            f"{package}/{filename} nie jest pokryty przez [tool.setuptools.package-data] — "
            f"non-editable `pip install .` nie wniesie tego pliku i runtime padnie na czystej "
            f"instalacji. Dopisz wzorzec obejmujący ten plik.")


def test_kazdy_asset_pakietu_wchodzi_do_frozen():
    """Druga droga dystrybucji: oba specy PyInstallera muszą zbierać te same rozszerzenia.
    Rozjazd stron jest cichy — `.exe` działa, wheel nie (albo odwrotnie)."""
    for spec in SPECS:
        text = (ROOT / spec).read_text(encoding="utf-8")
        assert 'collect_data_files("horreum"' in text, f"{spec}: brak zbiórki danych pakietu"
        for suffix in RESOURCE_SUFFIXES:
            assert f'"**/*{suffix}"' in text, (
                f"{spec}: `collect_data_files(\"horreum\")` nie bierze `**/*{suffix}` — "
                f"frozen zgubi assety tego typu")


def test_katalogi_assetow_sa_znajdowane_jako_paczki():
    """`package-data` działa TYLKO dla katalogów, które `packages.find` w ogóle znajdzie.
    Katalog assetów bez `__init__.py` wchodzi jako namespace package — a to zależy od
    `namespaces` (domyślnie włączone). Pin: gdyby ktoś je wyłączył, migracje wypadłyby z wheela."""
    find = _pyproject()["packages"]["find"]
    assert find.get("namespaces", True) is True, (
        "namespaces=false wyrzuci z wheela katalogi assetów bez `__init__.py` "
        "(dziś: horreum/schema/migrations)")
    assert any(fnmatch.fnmatch("horreum.gui.assets", pat) for pat in find["include"])
