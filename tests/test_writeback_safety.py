"""META-TRIPWIR (statyczny, AST) — druga klinga: MUTACJA PLIKÓW tylko w `writeback.py` (KROK 4).

Odpowiednik `test_repo_safety.py` (zapis do BAZY tylko w `repo.py`) przełożony na ZAPIS NA DYSK:
żaden moduł pakietu `horreum` POZA `writeback.py` nie mutuje plików usera. Odpowiednik zakazu
`os.rename`/`os.remove` poza `mover.py`/`eraser.py` Custosa. Faza skanu jest read-only (`safety.py`
pilnuje runtime); ten test pilnuje KODU statycznie.

Dopasowanie KWALIFIKOWANE (brief §4/R#3 — inaczej `str.replace`/`list.remove` dają fałszywe
trafienia, a `write_text`/aliasy — dziury):
- `os.replace/remove/rename/unlink/...` łapane TYLKO jako `os.<attr>` (Attribute na Name('os')) -
  goły `.replace` (str) / `.remove` (list) NIE jest mutacją pliku;
- alias importu `from os import replace as ...` / `from io import open as ...` śledzony;
- nazwy JEDNOZNACZNE łapane po gołym attr: `writeto`, `write_text`, `write_bytes`, `mkstemp`,
  `NamedTemporaryFile`, `CreateFileW`, `open_osfhandle`, mutatory `pathlib` (`unlink`, `rmdir`,
  `touch`, `symlink_to`, `hardlink_to`), oraz `shutil.*`, `numpy.save`/`np.save`;
- `Path.rename`/`Path.replace` po arności (jeden argument pozycyjny, bez nazwanych) - `str.replace`
  ma dwa, `dataclasses.replace` niesie nazwane;
- `open(...)`, `Path.open(...)`, `io.open(...)`, `os.fdopen(...)` z trybem piszącym (w/a/x/+)
  ALBO z trybem NIE-literałem (dynamiczny tryb to furtka: `mode = "r+b"; open(p, mode)`);
  `fits.open` - tryby mutujące astropy.

Wyjątki są po DOKŁADNEJ ścieżce modułu (Z8, 2026-09-26), nie po samej nazwie pliku - zagnieżdżony
`horreum/cokolwiek/writeback.py` nie jest klingą."""
import ast
from pathlib import Path

import pytest

import horreum

PKG = Path(horreum.__file__).parent
# Domy mutacji plików: `writeback.py` (druga klinga - nagłówki+rename, KROK 4), `projection.py`
# (trzecia klinga - link/kopia/katalog, KROK 6) oraz `raport.py` (czwarte drzwi - katalog raportu
# śladów i kopia klatki dla ASTAP, `MT-2`). Pętla pomija wszystkie (brief PLAN_projekcje §0).
DOORS = {PKG / "writeback.py", PKG / "projection.py", PKG / "raport.py"}

# os.<attr> — mutacje pliku (kwalifikowane przez moduł `os`, nie goły attr). `link`/`symlink`/`mkdir`/
# `makedirs` doszły z projekcją (KROK 6): tworzenie linków/katalogów to mutacja filesystemu.
# `write`/`pwrite`/`writev`/`pwritev`/`truncate`/`ftruncate`/`fdopen` doszły z ZAPISEM W MIEJSCU (O5,
# 2026-09-26): niskopoziomowy zapis po deskryptorze i obiekt pliku z deskryptora to ta sama mutacja
# bez trybu w `open`. `os.fsync` mutacją nie jest (utrwala to, co już zapisano) i zostaje poza listą.
OS_MUTATORS = {"replace", "remove", "rename", "unlink", "rmdir", "removedirs", "renames",
               "link", "symlink", "mkdir", "makedirs",
               "write", "pwrite", "writev", "pwritev", "truncate", "ftruncate", "fdopen"}
# nazwy jednoznaczne (goły attr wystarcza — nie kolidują z metodami str/list/dict). `flush` CELOWO
# pominięty: koliduje z lokalnymi funkcjami/Qt. `mkdir`/`makedirs` TAKŻE tu (KROK 6): domyka furtkę
# `Path(dst).mkdir()`. `CreateFileW`/`open_osfhandle` (O5): uchwyt Windows otwarty do zapisu przez
# ctypes (blokada współdzielenia zapisu w miejscu) omija `open` w całości.
BARE_MUTATORS = {"writeto", "write_text", "write_bytes", "mkstemp", "mkdtemp",
                 "NamedTemporaryFile", "TemporaryFile", "mkdir", "makedirs",
                 "CreateFileW", "open_osfhandle",
                 "unlink", "rmdir", "touch", "symlink_to", "hardlink_to"}
# `Path.rename(cel)`/`Path.replace(cel)` - nazwy wspólne z `str.replace` i `dataclasses.replace`,
# więc rozpoznawane po ARNOŚCI: dokładnie jeden argument pozycyjny i żadnego nazwanego. `str.replace`
# ma zawsze co najmniej dwa pozycyjne, `dataclasses.replace`/`datetime.replace` niosą zmiany nazwane.
# Rozpoznanie po typie odbiorcy (`Path(...)`, adnotacja) przepuściłoby `p.rename(q)` na zmiennej.
PATH_RENAMERS = {"rename", "replace"}
# moduły, których KAŻDE wywołanie mutujące łapiemy po `<mod>.<attr>`.
MOD_MUTATORS = {"shutil": {"copy", "copy2", "copyfile", "move", "rmtree", "copytree"},
                "np": {"save", "savez", "savetxt", "savez_compressed"},
                "numpy": {"save", "savez", "savetxt", "savez_compressed"}}
WRITE_MODES = set("wax+")             # tryb open() piszący
# tryby fits.open() mutujące plik in-place (writeback używa 'readonly' → czysty).
FITS_WRITE_MODES = {"update", "append", "ostream", "rw", "rw+"}


def _py_files():
    return sorted(PKG.rglob("*.py"))


def _aliases(tree):
    """Lokalne nazwy furtek importu: `from os import replace as X` (mutatory `os`) oraz
    `from io import open as X` / `from builtins import open as X` (otwarcie pliku)."""
    os_aliases, open_aliases = set(), {"open"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for a in node.names:
                if node.module == "os" and a.name in OS_MUTATORS:
                    os_aliases.add(a.asname or a.name)
                if node.module in ("io", "builtins", "codecs") and a.name == "open":
                    open_aliases.add(a.asname or a.name)
    return os_aliases, open_aliases


def _mode_arg(call, pos):
    mode = call.args[pos] if len(call.args) > pos else None
    for kw in call.keywords:
        if kw.arg == "mode":
            mode = kw.value
    return mode


def _mode_verdict(mode, write_modes):
    """None = tryb czytający (albo brak trybu), inaczej opis: literał piszący albo tryb dynamiczny."""
    if mode is None:
        return None
    if not (isinstance(mode, ast.Constant) and isinstance(mode.value, str)):
        return "<tryb dynamiczny>"
    return "<tryb pisania>" if write_modes(mode.value) else None


def _pisze(value):
    return any(ch in WRITE_MODES for ch in value)


def _file_mutators(tree, aliases):
    """Wydaj opisy wywołań mutujących plik w drzewie AST."""
    os_aliases, open_aliases = aliases
    for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call)):
        f = call.func
        if isinstance(f, ast.Attribute):
            attr, base = f.attr, f.value
            if isinstance(base, ast.Name) and base.id == "os" and attr in OS_MUTATORS:
                yield f"os.{attr}(...)"
            elif (isinstance(base, ast.Name) and base.id in MOD_MUTATORS
                  and attr in MOD_MUTATORS[base.id]):
                yield f"{base.id}.{attr}(...)"
            elif attr in BARE_MUTATORS:
                yield f".{attr}(...)"
            elif attr in PATH_RENAMERS and len(call.args) == 1 and not call.keywords:
                yield f".{attr}(...)"
            elif attr == "open":
                # `fits.open(path, mode)` - tryby astropy; `io.open(path, mode)` - jak `open`;
                # `Path(...).open(mode)` - tryb jest PIERWSZYM argumentem.
                if isinstance(base, ast.Name) and base.id == "fits":
                    werdykt = _mode_verdict(_mode_arg(call, 1), lambda m: m in FITS_WRITE_MODES)
                elif isinstance(base, ast.Name) and base.id in ("io", "builtins", "codecs"):
                    werdykt = _mode_verdict(_mode_arg(call, 1), _pisze)
                else:
                    werdykt = _mode_verdict(_mode_arg(call, 0), _pisze)
                if werdykt is not None:
                    yield f".open(..., {werdykt})"
        elif isinstance(f, ast.Name):
            if f.id in os_aliases or f.id in BARE_MUTATORS:
                yield f"{f.id}(...)"        # alias os.replace / bezpośredni mkstemp
            elif f.id in open_aliases:
                werdykt = _mode_verdict(_mode_arg(call, 1), _pisze)
                if werdykt is not None:
                    yield f"open(..., {werdykt})"


def test_mutacja_plikow_tylko_w_writeback():
    """Statyczny meta-tripwir: żaden moduł poza klingami plików (`writeback.py`/`projection.py`,
    po dokładnej ścieżce) nie mutuje plików usera."""
    offenders = []
    for src in _py_files():
        if src in DOORS:
            continue
        tree = ast.parse(src.read_text(encoding="utf-8"))
        for desc in _file_mutators(tree, _aliases(tree)):
            offenders.append(f"{src.relative_to(PKG)}: {desc}")
    assert not offenders, f"mutacja plików poza klingami plików ({sorted(DOORS)}): {offenders}"


def test_klinga_plikow_istnieje():
    """Pozytywna asercja zakresu: `writeback.py` REALNIE zawiera `os.replace` (klinga ma ostrze).
    Gdyby ktoś usunął zapis pliku z writeback.py, warstwa byłaby martwa — ten test to złapie."""
    tree = ast.parse((PKG / "writeback.py").read_text(encoding="utf-8"))
    found = list(_file_mutators(tree, _aliases(tree)))
    assert any("os.replace" in d for d in found), "writeback.py nie zawiera os.replace — klinga martwa"


def _funkcja(tree, nazwa):
    return next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == nazwa)


def _wywolania_w_funkcjach(tree):
    """[(nazwa funkcji najwyższego poziomu | '<moduł>', ast.Call)] - każde wywołanie z funkcją, w której
    stoi (zagnieżdżone definicje liczą się do funkcji zewnętrznej)."""
    wynik = []
    for wezel in tree.body:
        nazwa = wezel.name if isinstance(wezel, (ast.FunctionDef, ast.ClassDef)) else "<moduł>"
        wynik.extend((nazwa, c) for c in ast.walk(wezel) if isinstance(c, ast.Call))
    return wynik


def _tryb(call, pos):
    mode = _mode_arg(call, pos)
    return mode.value if isinstance(mode, ast.Constant) and isinstance(mode.value, str) else None


def _zapis_w_klindze(tree):
    """Analiza zapisu wewnątrz klingi: `(naruszenia, otwarcia_do_zapisu, funkcje_z_write)`.
    Naruszenie: gołe `open` z trybem `+`, `open` z trybem dynamicznym, `os.fdopen` w trybie innym niż
    `r+b`, `os.write`/`pwrite`/`writev`/`pwritev` - wszystko z nazwą funkcji, w której stoi."""
    otwarcia, zapisy, naruszenia = set(), set(), []
    for funkcja, c in _wywolania_w_funkcjach(tree):
        f = c.func
        if isinstance(f, ast.Name) and f.id == "open":
            tryb = _tryb(c, 1)
            if tryb is None and _mode_arg(c, 1) is not None:
                naruszenia.append(f"{funkcja}: open z trybem dynamicznym")
            elif tryb and _pisze(tryb):
                otwarcia.add((funkcja, "open"))
                if "+" in tryb:
                    naruszenia.append(f"{funkcja}: gołe open(..., {tryb!r})")
        elif isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "os":
            if f.attr == "fdopen":
                otwarcia.add((funkcja, "os.fdopen"))
                if _tryb(c, 1) != "r+b":
                    naruszenia.append(f"{funkcja}: os.fdopen z trybem {_tryb(c, 1)!r}")
            elif f.attr in ("write", "pwrite", "writev", "pwritev"):
                naruszenia.append(f"{funkcja}: os.{f.attr}")
        elif isinstance(f, ast.Attribute) and f.attr == "write":
            zapisy.add(funkcja)
    return naruszenia, otwarcia, zapisy


# Gdzie w klindze WOLNO otworzyć plik do zapisu i gdzie wolno pisać bajty (astra Z8). Każde nowe
# miejsce zapisu w `writeback.py` przewraca test i wymaga świadomego dopisania tutaj.
_OTWARCIA_DO_ZAPISU = {("_exclusive", "os.fdopen"), ("_write_xisf_file", "open")}
_ZAPISY_BAJTOW = {"_apply_inplace", "_write_xisf_file"}


def test_zapis_w_klindze_tylko_w_dozwolonych_funkcjach():
    """Z8, KONKRETNIE i W OBIE STRONY: w `writeback.py` (1) uchwyt zapisu w miejscu powstaje wyłącznie
    w `_exclusive` (`CreateFileW` z blokadą współdzielenia + `os.fdopen(fd, "r+b")`), (2) jedyne inne
    otwarcie do zapisu to plik tymczasowy drogi atomowej XISF, (3) gołego `open(..., "r+b")` nie ma
    NIGDZIE - gołe `open` nie odcina innych piszących (Z2), (4) `.write(...)` stoi wyłącznie
    w `_apply_inplace` i `_write_xisf_file`, `os.write` - nigdzie. Każde złamanie wskazuje funkcję."""
    tree = ast.parse((PKG / "writeback.py").read_text(encoding="utf-8"))
    naruszenia, otwarcia, zapisy = _zapis_w_klindze(tree)
    assert not naruszenia, naruszenia
    assert otwarcia == _OTWARCIA_DO_ZAPISU, otwarcia
    assert zapisy == _ZAPISY_BAJTOW, zapisy
    excl = _funkcja(tree, "_exclusive")
    assert any(isinstance(c.func, ast.Attribute) and c.func.attr == "CreateFileW"
               for c in ast.walk(excl) if isinstance(c, ast.Call))


@pytest.mark.parametrize("kod, fragment", [
    ("def zla(p):\n    open(p, 'r+b')\n", "zla: gołe open(..., 'r+b')"),
    ("def zla(fd):\n    os.write(fd, b'x')\n", "zla: os.write"),
    ("def zla(fd):\n    os.fdopen(fd, 'wb')\n", "zla: os.fdopen z trybem 'wb'"),
    ("def zla(p, m):\n    open(p, m)\n", "zla: open z trybem dynamicznym"),
])
def test_analiza_zapisu_w_klindze_lapie_naruszenia(kod, fragment):
    """Negatywny dowód na TEJ SAMEJ funkcji analizy, której używa test wyżej (poprzednia asercja
    szukała tekstu, którego analizator nie zwracał)."""
    assert fragment in _zapis_w_klindze(ast.parse(kod))[0]


def test_analiza_zapisu_widzi_write_poza_dozwolonymi():
    _, _, zapisy = _zapis_w_klindze(ast.parse("def inna(fh):\n    fh.write(b'x')\n"))
    assert zapisy == {"inna"} and not zapisy <= _ZAPISY_BAJTOW


def test_klinga_projekcji_istnieje():
    """Pozytywna asercja zakresu (bliźniak): `projection.py` REALNIE zawiera `os.link` (trzecia klinga
    ma ostrze). Gdyby ktoś wyjął tworzenie linku z projekcji, warstwa byłaby martwa — ten test to
    złapie (a rozszerzenie `OS_MUTATORS` bez realnego użycia dałoby fałszywe poczucie pokrycia)."""
    tree = ast.parse((PKG / "projection.py").read_text(encoding="utf-8"))
    found = list(_file_mutators(tree, _aliases(tree)))
    assert any("os.link" in d for d in found), "projection.py nie zawiera os.link — klinga martwa"


def _mutatory_po_funkcjach(tree):
    """{nazwa węzła najwyższego poziomu: [opisy mutacji]} - tylko węzły z co najmniej jedną mutacją."""
    aliases = _aliases(tree)
    wynik = {}
    for wezel in tree.body:
        nazwa = wezel.name if isinstance(wezel, (ast.FunctionDef, ast.ClassDef)) else "<moduł>"
        found = list(_file_mutators(wezel, aliases))
        if found:
            wynik.setdefault(nazwa, []).extend(found)
    return wynik


# Gdzie w czwartych drzwiach WOLNO mutować plik (`MT-2`): zakładanie katalogu, sprzątanie po
# odmowie i zapis przez plik tymczasowy. Klasa `Raport` nie mutuje sama - każda jej ścieżka idzie
# przez te funkcje po `Raport._cel`. Nowe miejsce mutacji przewraca test i wymaga dopisania tutaj.
_RAPORT_MUTACJE = {
    "_utworz_katalog": {"os.makedirs(...)"},
    "_usun_pusty": {"os.rmdir(...)"},
    "_zapisz_plik": {"open(..., <tryb pisania>)", "os.remove(...)", "os.rename(...)"},
    "_usun_plik": {"os.remove(...)"},
    # AR-51: przypięcie katalogu raportu - uchwyt do LISTOWANIA bez FILE_SHARE_DELETE, nie zapis
    "_przypnij": {".CreateFileW(...)"},
}


def _mapa_mutacji(zrodlo):
    """{funkcja najwyższego poziomu: zbiór opisów mutacji} - ta sama analiza dla żywego `raport.py`
    i dla jego zmodyfikowanej kopii w teście negatywnym."""
    return {k: set(v) for k, v in _mutatory_po_funkcjach(ast.parse(zrodlo)).items()}


def test_klinga_raportu_istnieje_i_mutuje_tylko_w_dozwolonych_funkcjach():
    """Czwarte drzwi (`MT-2`) mają ostrze (publikacja przez `os.rename` - bez nadpisania celu)
    i W OBIE STRONY mutują wyłącznie w funkcjach z `_RAPORT_MUTACJE`; plik otwierają do zapisu tylko
    jako NOWY (`xb`) - żadnego `w`/`a`/`+`, czyli żadnego nadpisania ani dopisania do istniejącego
    pliku."""
    zrodlo = (PKG / "raport.py").read_text(encoding="utf-8")
    tree = ast.parse(zrodlo)
    found = _mapa_mutacji(zrodlo)
    assert found == _RAPORT_MUTACJE, found
    tryby = {_tryb(c, 1) for _, c in _wywolania_w_funkcjach(tree)
             if isinstance(c.func, ast.Name) and c.func.id == "open" and _mode_arg(c, 1) is not None}
    assert tryby == {"xb", "rb"}, tryby


def test_mutatory_po_funkcjach_widzi_metode_klasy():
    """Negatywny dowód analizy wyżej: mutacja w metodzie klasy przypisana jest klasie, więc
    `os.remove` dopisany wprost w `Raport` przewraca test drzwi."""
    tree = ast.parse("class Raport:\n    def f(self, p):\n        os.remove(p)\n")
    assert _mutatory_po_funkcjach(tree) == {"Raport": ["os.remove(...)"]}


@pytest.mark.parametrize("cialo, opis", [
    ("Path(p).unlink()", ".unlink(...)"),
    ("Path(p).rename(q)", ".rename(...)"),
    ("p.replace(q)", ".replace(...)"),
    ("Path(p).rmdir()", ".rmdir(...)"),
    ("Path(p).touch()", ".touch(...)"),
    ("Path(p).write_text('x')", ".write_text(...)"),
    ("Path(p).open('wb')", ".open(..., <tryb pisania>)"),
])
def test_mutacja_pathlib_w_nowej_funkcji_raportu_przewraca_bramke(cialo, opis):
    """Negatywny dowód bramki drzwi raportu na KOPII żywego źródła w pamięci: mutacja `pathlib`
    dopisana w osobnej funkcji zmienia mapę, więc `found == _RAPORT_MUTACJE` czerwienieje."""
    zrodlo = (PKG / "raport.py").read_text(encoding="utf-8")
    found = _mapa_mutacji(zrodlo + f"\n\ndef _wyciek(p, q):\n    {cialo}\n")
    assert found != _RAPORT_MUTACJE and found["_wyciek"] == {opis}


def test_dopasowanie_nie_lapie_str_list_methods():
    """Regresja fałszywych trafień (R#3): `str.replace`/`list.remove`, odczyt przez `open`/`Path.open`
    i `fits.open(..., mode="readonly")` NIE są mutacją pliku."""
    sample = ast.parse(
        "s = 'a'.replace('a','b')\n"
        "lst = [1]; lst.remove(1)\n"
        "v = value.replace(\"''\", \"'\")\n"
        "fh = open(p, 'rb'); g = open(p)\n"
        "h = path.open('rb'); k = path.open()\n"
        "fits.open(p, mode='readonly', memmap=False)\n"
        "d = dataclasses.replace(ident, alias_norm=None)\n"
        "t = dt.replace(year=2020)\n")
    assert not list(_file_mutators(sample, _aliases(sample)))


@pytest.mark.parametrize("kod, opis", [
    ("with path.open('r+b') as fh:\n    fh.write(b)\n", ".open(..., <tryb pisania>)"),
    ("mode = 'r+b'\nwith open(path, mode) as fh:\n    pass\n", "open(..., <tryb dynamiczny>)"),
    ("import io\nio.open(path, 'wb')\n", ".open(..., <tryb pisania>)"),
    ("from io import open as otworz\notworz(path, 'a')\n", "open(..., <tryb pisania>)"),
    ("fh = os.fdopen(fd, 'r+b')\n", "os.fdopen(...)"),
    ("os.write(fd, b'x')\n", "os.write(...)"),
    ("os.ftruncate(fd, 0)\n", "os.ftruncate(...)"),
    ("h = k32.CreateFileW(p, 0xC0000000, 1, None, 3, 0x80, None)\n", ".CreateFileW(...)"),
    ("fits.open(p, mode='update')\n", ".open(..., <tryb pisania>)"),
    ("fits.open(p, mode=tryb)\n", ".open(..., <tryb dynamiczny>)"),
    ("from os import replace as podmien\npodmien(a, b)\n", "podmien(...)"),
])
def test_furtki_mutacji_sa_lapane(kod, opis):
    """Z8: obejścia wskazane w recenzji (i ich krewni) są wykrywane."""
    tree = ast.parse(kod)
    assert opis in list(_file_mutators(tree, _aliases(tree)))


def test_wyjatek_po_dokladnej_sciezce_nie_po_nazwie():
    """Z8: zagnieżdżony moduł o nazwie klingi NIE jest klingą."""
    assert PKG / "gui" / "writeback.py" not in DOORS and PKG / "writeback.py" in DOORS
    assert PKG / "gui" / "raport.py" not in DOORS and PKG / "raport.py" in DOORS

