"""META-TRIPWIR (statyczny, AST) — druga klinga: MUTACJA PLIKÓW tylko w `writeback.py` (KROK 4).

Odpowiednik `test_repo_safety.py` (zapis do BAZY tylko w `repo.py`) przełożony na ZAPIS NA DYSK:
żaden moduł pakietu `horreum` POZA `writeback.py` nie mutuje plików usera. Odpowiednik zakazu
`os.rename`/`os.remove` poza `mover.py`/`eraser.py` Custosa. Faza skanu jest read-only (`safety.py`
pilnuje runtime); ten test pilnuje KODU statycznie.

Dopasowanie KWALIFIKOWANE (brief §4/R#3 — inaczej `str.replace`/`list.remove` dają fałszywe
trafienia, a `write_text`/aliasy — dziury):
- `os.replace/remove/rename/unlink` łapane TYLKO jako `os.<attr>` (Attribute na Name('os')) — goły
  `.replace` (str) / `.remove` (list) NIE jest mutacją pliku;
- alias importu `from os import replace as ...` śledzony (rzadki, ale domyka furtkę);
- nazwy JEDNOZNACZNE łapane po gołym attr: `writeto`, `write_text`, `write_bytes`, `mkstemp`,
  `NamedTemporaryFile`, `flush`, oraz `shutil.*`, `numpy.save`/`np.save`;
- `open(..., <tryb z w/a/x/+>)` (arg-literał trybu)."""
import ast
from pathlib import Path

import horreum

PKG = Path(horreum.__file__).parent
# Domy mutacji plików: `writeback.py` (druga klinga — nagłówki+rename, KROK 4) oraz `projection.py`
# (trzecia klinga — link/kopia/katalog, KROK 6). Pętla pomija OBA (brief PLAN_projekcje §0).
DOORS = {"writeback.py", "projection.py"}

# os.<attr> — mutacje pliku (kwalifikowane przez moduł `os`, nie goły attr). `link`/`symlink`/`mkdir`/
# `makedirs` doszły z projekcją (KROK 6): tworzenie linków/katalogów to mutacja filesystemu.
OS_MUTATORS = {"replace", "remove", "rename", "unlink", "rmdir", "removedirs", "renames",
               "link", "symlink", "mkdir", "makedirs"}
# nazwy jednoznaczne (goły attr wystarcza — nie kolidują z metodami str/list/dict). `flush` CELOWO
# pominięty: koliduje z lokalnymi funkcjami/Qt, a writeback pisze przez writeto+os.replace (nie
# hdul.flush). In-place astropy łapiemy przez tryb `fits.open` (niżej), nie przez flush. `mkdir`/
# `makedirs` TAKŻE tu (KROK 6): domyka furtkę `Path(dst).mkdir()` (bare attr, jednoznaczny — brak
# metody str/list o tej nazwie); grep potwierdził ZERO użyć w rdzeniu poza `projection.py`.
BARE_MUTATORS = {"writeto", "write_text", "write_bytes", "mkstemp", "mkdtemp",
                 "NamedTemporaryFile", "TemporaryFile", "mkdir", "makedirs"}
# moduły, których KAŻDE wywołanie mutujące łapiemy po `<mod>.<attr>`.
MOD_MUTATORS = {"shutil": {"copy", "copy2", "copyfile", "move", "rmtree", "copytree"},
                "np": {"save", "savez", "savetxt", "savez_compressed"},
                "numpy": {"save", "savez", "savetxt", "savez_compressed"}}
WRITE_MODES = set("wax+")             # tryb open() piszący
# tryby fits.open() mutujące plik in-place (writeback używa 'readonly' → czysty).
FITS_WRITE_MODES = {"update", "append", "ostream", "rw", "rw+"}


def _py_files():
    return sorted(PKG.rglob("*.py"))


def _os_aliases(tree):
    """Nazwy zaimportowane jako `from os import replace as X` (alias furtki) → zbiór lokalnych nazw."""
    aliases = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "os":
            for a in node.names:
                if a.name in OS_MUTATORS:
                    aliases.add(a.asname or a.name)
    return aliases


def _open_writes(call):
    """`open(path, 'w'|'a'|'x'|'r+'...)` z literałem trybu zawierającym w/a/x/+ → True."""
    if not (isinstance(call.func, ast.Name) and call.func.id == "open"):
        return False
    mode = call.args[1] if len(call.args) >= 2 else None
    for kw in call.keywords:
        if kw.arg == "mode":
            mode = kw.value
    return (isinstance(mode, ast.Constant) and isinstance(mode.value, str)
            and any(ch in WRITE_MODES for ch in mode.value))


def _fits_open_writes(call):
    """`fits.open(path, mode='update'/'append'/...)` (mutacja in-place) → True. Wykrywa attr `open`
    z literałem trybu piszącego (writeback używa 'readonly' → nie łapane)."""
    f = call.func
    if not (isinstance(f, ast.Attribute) and f.attr == "open"):
        return False
    mode = None
    if len(call.args) >= 2:
        mode = call.args[1]
    for kw in call.keywords:
        if kw.arg == "mode":
            mode = kw.value
    return (isinstance(mode, ast.Constant) and isinstance(mode.value, str)
            and mode.value in FITS_WRITE_MODES)


def _file_mutators(tree, aliases):
    """Wydaj opisy wywołań mutujących plik w drzewie AST."""
    for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call)):
        f = call.func
        if isinstance(f, ast.Attribute):
            attr = f.attr
            base = f.value
            # os.<mutator> — kwalifikowane (odsiewa str.replace / list.remove)
            if isinstance(base, ast.Name) and base.id == "os" and attr in OS_MUTATORS:
                yield f"os.{attr}(...)"
            elif (isinstance(base, ast.Name) and base.id in MOD_MUTATORS
                  and attr in MOD_MUTATORS[base.id]):
                yield f"{base.id}.{attr}(...)"
            elif attr in BARE_MUTATORS:
                yield f".{attr}(...)"
            elif _fits_open_writes(call):
                yield f".open(mode=<pisanie>)"
        elif isinstance(f, ast.Name):
            if f.id in aliases or f.id in BARE_MUTATORS:
                yield f"{f.id}(...)"        # alias os.replace / bezpośredni mkstemp
            elif _open_writes(call):
                yield "open(..., <tryb pisania>)"


def test_mutacja_plikow_tylko_w_writeback():
    """Statyczny meta-tripwir: żaden moduł poza klingami plików (`writeback.py`/`projection.py`)
    nie mutuje plików usera."""
    offenders = []
    for src in _py_files():
        if src.name in DOORS:
            continue
        tree = ast.parse(src.read_text(encoding="utf-8"))
        aliases = _os_aliases(tree)
        for desc in _file_mutators(tree, aliases):
            offenders.append(f"{src.name}: {desc}")
    assert not offenders, f"mutacja plików poza klingami plików ({sorted(DOORS)}): {offenders}"


def test_klinga_plikow_istnieje():
    """Pozytywna asercja zakresu: `writeback.py` REALNIE zawiera `os.replace` (klinga ma ostrze).
    Gdyby ktoś usunął zapis pliku z writeback.py, warstwa byłaby martwa — ten test to złapie."""
    tree = ast.parse((PKG / "writeback.py").read_text(encoding="utf-8"))
    found = list(_file_mutators(tree, _os_aliases(tree)))
    assert any("os.replace" in d for d in found), "writeback.py nie zawiera os.replace — klinga martwa"


def test_klinga_projekcji_istnieje():
    """Pozytywna asercja zakresu (bliźniak): `projection.py` REALNIE zawiera `os.link` (trzecia klinga
    ma ostrze). Gdyby ktoś wyjął tworzenie linku z projekcji, warstwa byłaby martwa — ten test to
    złapie (a rozszerzenie `OS_MUTATORS` bez realnego użycia dałoby fałszywe poczucie pokrycia)."""
    tree = ast.parse((PKG / "projection.py").read_text(encoding="utf-8"))
    found = list(_file_mutators(tree, _os_aliases(tree)))
    assert any("os.link" in d for d in found), "projection.py nie zawiera os.link — klinga martwa"


def test_dopasowanie_nie_lapie_str_list_methods():
    """Regresja fałszywych trafień (R#3): `str.replace`/`list.remove` w rdzeniu NIE są mutacją pliku.
    Dowód, że realne (`filter_engine.py`/`grid.py`/`scan.py`) przechodzą — inaczej bramka byłaby
    czerwona od dnia zero."""
    sample = ast.parse(
        "s = 'a'.replace('a','b')\n"
        "lst = [1]; lst.remove(1)\n"
        "v = value.replace(\"''\", \"'\")\n")
    assert not list(_file_mutators(sample, set()))
