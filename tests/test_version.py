"""META-TRIPWIR — numer wersji ma JEDNEGO właściciela, a wydanie nie może wyjść z rozjazdem.

Prow.: opublikowany `Horreum-0.4.0-windows-x64.exe` na `horreum --version` odpowiadał
`horreum 0.3.2` — literał w `horreum/__init__.py` przespał dwa wydania, a to JEDYNA droga,
którą użytkownik sprawdza, co ma. Ta sama klasa błędu co dług pakowania: jeden fakt w dwóch
miejscach, rozjazd cichy do pierwszej publikacji.

Pilnowane są WSZYSTKIE cztery powierzchnie numeru: kod (co mówi program), `pyproject.toml`
(co niesie wheel — jedyny właściciel), tag gita (co wisi jako wydanie) i specy PyInstallera
(czy frozen w ogóle ma z czego numer przeczytać). Test czyta `pyproject.toml` przez `tomllib`,
a runtime regexem — dwa niezależne odczyty, żeby bramka nie potwierdzała sama siebie."""
import subprocess
from pathlib import Path

import pytest

import horreum
from horreum import cli

try:
    import tomllib
except ImportError:                                   # <3.11 — bramka jest dev-only, nie runtime
    tomllib = None

ROOT = Path(horreum.__file__).resolve().parent.parent
SPECS = ("packaging/horreum.spec", "packaging/horreum-onefile.spec")


def _pyproject_version():
    if tomllib is None:
        pytest.skip("tomllib wymaga Pythona 3.11+")
    with open(ROOT / "pyproject.toml", "rb") as fh:
        return tomllib.load(fh)["project"]["version"]


def _as_tuple(text):
    """`v0.2` i `0.4.0` na wspólną miarę — brakujące człony to zera."""
    parts = [int(p) for p in text.lstrip("v").split(".")]
    return tuple(parts + [0] * (3 - len(parts)))


def _git(*args):
    """Wynik gita albo `None`, gdy gita/repo nie ma (wheel u kontrybutora, sandbox CI)."""
    try:
        out = subprocess.run(("git",) + args, cwd=ROOT, capture_output=True, text=True)
    except OSError:
        return None
    return out.stdout if out.returncode == 0 else None


def test_kod_mowi_to_samo_co_pyproject():
    """Sedno bugu: `horreum.__version__` MUSI pochodzić z `pyproject.toml`, nie z literału."""
    assert horreum.__version__ == _pyproject_version()


def test_cli_version_wypisuje_numer_wlasciciela(capsys):
    """Powierzchnia, którą sprawdza użytkownik — `horreum --version` na wprost."""
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--version"])
    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"horreum {_pyproject_version()}"


def test_fallback_gologo_klonu_czyta_pyproject(monkeypatch):
    """Klon bez instalacji nie ma metadanych — numer idzie wprost z pliku właściciela.
    Bez tego testu gałąź fallbacku nigdy by się w bateri nie wykonała (tu paczka JEST
    zainstalowana), a to ona strzeże, żeby nie wrócił zaszyty literał."""
    import importlib.metadata as meta

    def _brak(name):
        raise meta.PackageNotFoundError(name)

    monkeypatch.setattr(meta, "version", _brak)
    assert horreum._read_version() == _pyproject_version()


def test_najnowszy_tag_nie_wyprzedza_pyproject():
    """Tag `vX.Y.Z` większy niż `pyproject` = wydanie wypuszczone z numerem, którego kod nie zna
    (dokładnie sytuacja `.exe` 0.4.0 mówiącego 0.3.2). `pyproject` wolno WYPRZEDZAĆ tagi —
    tak wygląda praca nad kolejnym wydaniem."""
    tags = _git("tag", "--list", "v*")
    if tags is None:
        pytest.skip("brak gita albo repozytorium — bramka tagu jest dev-only")
    parsed = [_as_tuple(t.strip()) for t in tags.split() if t.strip()]
    if not parsed:
        pytest.skip("repozytorium bez tagów wydań")
    assert max(parsed) <= _as_tuple(_pyproject_version()), (
        "najnowszy tag wydania jest WYŻSZY niż wersja w pyproject.toml — albo tag poszedł "
        "przed podbiciem numeru, albo podbicie cofnięto; wheel i .exe skłamią użytkownikowi")


def test_oba_specy_wnosza_metadane_do_frozen():
    """Frozen czyta numer z metadanych paczki — a te wchodzą do exe TYLKO przez `copy_metadata`.
    Bez tego `.exe` odpowiada „nieznana”, czyli dokładnie tam, gdzie bug był widoczny."""
    for spec in SPECS:
        text = (ROOT / spec).read_text(encoding="utf-8")
        assert 'copy_metadata("horreum")' in text, (
            f"{spec}: brak `copy_metadata(\"horreum\")` — frozen nie będzie miał skąd wziąć "
            f"numeru wersji")


def test_build_zewnetrzny_ma_bramke_tagu():
    """PIĄTA POWIERZCHNIA NUMERU — nie zgodność czterech zapisów ze sobą, tylko zgodność
    ARTEFAKTU z drzewem, z którego powstał (decyzja Z. 2026-08-08: „buildy zewnętrzne powinny być
    zawsze na tagu, wersjonowane").

    Cztery pozostałe testy tego pliku pilnują, żeby kod, `pyproject`, tag i specy mówiły TO SAMO —
    i wszystkie przechodzą na drzewie 11 commitów za tagiem, bo żaden nie pyta, czy exe powstał
    z wydania. Bez tej bramki `-Onefile` zamraża tytuł „Horreum 0.6.0" na kodzie, którego wydane
    0.6.0 nigdy nie miało (zmierzone 2026-08-08).

    Test sprawdza OBECNOŚĆ mechanizmu, nie jego treść — pełne zachowanie bramki dowodzi się
    uruchomieniem (skrypt odmawia poza tagiem). Chodzi o to, żeby usunięcie przełącznika
    przewróciło baterię, a nie wyszło dopiero przy wydaniu."""
    text = (ROOT / "packaging/build.ps1").read_text(encoding="ascii")
    assert "[switch]$Release" in text, "build.ps1 stracił przełącznik -Release"
    assert "git tag --points-at HEAD" in text, (
        "build.ps1 nie sprawdza już, czy HEAD stoi na tagu — zewnętrzny build mógłby wyjść "
        "z dowolnego stanu drzewa")
    assert "--untracked-files=no" in text, (
        "build.ps1 nie sprawdza już czystości drzewa — PyInstaller zamraża drzewo robocze, "
        "nie tag, więc brudny plik śledzony trafiłby do wydania")
