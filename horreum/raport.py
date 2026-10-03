"""CZWARTE DRZWI - jedyne miejsce zapisu RAPORTU poza bazą (dług `MT-2`, wariant O1).

Raport detektora śladów (`horreum.streaks`: CSV, JSON, wycinki) i robocza kopia klatki dla ASTAP
(`-extract2`/`-wcs` piszą `.wcs/.ini/.csv` OBOK pliku, więc rozwiązuje się wyłącznie kopię) mają
wspólny problem: pliki trzeba gdzieś położyć, a mutacja plików w pakiecie żyje tylko w drzwiach
pilnowanych przez meta-tripwir AST (`tests/test_writeback_safety.py`, `DOORS`). Rdzeń `streaks.py`
zostaje czysty - oddaje bajty w pamięci, a wołający podaje je tutaj.

Drzwi są WĄSKIE i sprawdzalne:
- `otworz` tworzy katalog raportu (albo przyjmuje istniejący PUSTY) i odmawia, gdy leży on
  w katalogu któregokolwiek pliku wejścia albo pod nim, albo pod korzeniem chronionym (katalog
  `--folder`, korzeń archiwum). Odmowa przychodzi PRZED pierwszym zapisem.
- `Raport.zapisz_tekst` / `zapisz_bajty` / `kopia_dla_astap` piszą wyłącznie POD katalogiem raportu:
  nazwa jest względna, bez `..`, bez dysku i bez `:` (strumień NTFS), a katalog docelowy po
  rozwiązaniu dowiązań wciąż leży pod katalogiem raportu. Plik istniejący = odmowa, nie nadpisanie.
- Zapis idzie przez plik tymczasowy tworzony wyłącznie jako NOWY (`xb`) i `os.rename`: przerwany
  zapis nie zostawia uciętego pliku o wyglądzie gotowego, a publikacja jest atomowym „tylko gdy
  celu nie ma" (na Windows `os.rename` nie zastępuje istniejącego pliku) - cel, który powstał
  w trakcie zapisu (drugi proces w tym samym `--out`), to odmowa, nie nadpisanie.
- Korzenie chronione (`chronione`) podaje wołający ZAWSZE i jawnie - zapomniany katalog `--folder`
  dałby raport wewnątrz źródła; pusta krotka znaczy „chroń tylko katalogi plików wejścia".
- Kopia dla ASTAP bierze wyłącznie plik zgłoszony w `wejscia` - drzwi nie kopiują dowolnych ścieżek.

Porównanie położenia idzie DWIEMA drogami: po `normcase(abspath)` (Windows nie rozróżnia
wielkości liter, a `abspath` nie zamienia dysku mapowanego na UNC) oraz po `normcase(realpath)`
(dowiązanie albo junction). Wobec źródła odmawia, gdy KTÓRAKOLWIEK mówi „pod" (`_pod`); zapis pod
raportem przechodzi, gdy OBIE mówią „pod" (`_wewnatrz`) - stąd ani junction do źródła jako `--out`,
ani dowiązanie wyprowadzające z raportu na zewnątrz.
Granica katalogu przez `os.path.commonpath`, nie `startswith` - `dane_raport` nie leży pod `dane`.

Ścieżek prywatnych w kodzie nie ma (repo publiczne): korzeń archiwum podaje wołający w `chronione`.
"""
from __future__ import annotations

import os

ASTAP_DIR = "astap"          # podkatalog raportu z kopiami klatek do rozwiązania przez ASTAP
_CHUNK = 1 << 20


class RaportOdmowa(ValueError):
    """Odmowa drzwi raportu: katalog albo nazwa wychodzi poza dozwolone miejsce, plik już istnieje,
    źródło kopii nie jest zgłoszonym wejściem. Nic nie zostało zapisane w miejscu odmowy."""


def _formy(path):
    """Dwie formy porównania ścieżki: literowa (`abspath`) i po rozwiązaniu dowiązań (`realpath`)."""
    return (os.path.normcase(os.path.abspath(path)),
            os.path.normcase(os.path.realpath(path)))


def _pod_w_formach(path, root):
    """Dla każdej z form `_formy`: czy `path` jest katalogiem `root` albo leży pod nim."""
    out = []
    for p, r in zip(_formy(path), _formy(root)):
        try:
            out.append(os.path.commonpath([p, r]) == r)
        except ValueError:                 # różne dyski - `path` nie może leżeć pod `root`
            out.append(False)
    return out


def _pod(path, root):
    """Odmowa źródła: `path` pod `root` w KTÓREJKOLWIEK formie (dowiązanie do źródła też się liczy)."""
    return any(_pod_w_formach(path, root))


def _wewnatrz(path, root):
    """Zgoda zapisu: `path` pod `root` w KAŻDEJ formie (dowiązanie wyprowadzające na zewnątrz nie)."""
    return all(_pod_w_formach(path, root))


def odmowa_katalogu(out, wejscia, *, chronione):
    """Powód odmowy katalogu raportu `out` albo `None`. Czysty odczyt.

    Chronione są: katalog każdego pliku z `wejscia` i każdy korzeń z `chronione` (katalog wejściowy
    trybu katalogu, korzeń archiwum). `out` w którymś z nich albo pod nim = odmowa; `out` istniejący
    jako plik albo niepusty katalog = odmowa (raport nie miesza się z cudzą treścią)."""
    roots = {os.path.dirname(os.path.abspath(f)) for f in wejscia} | {os.path.abspath(c) for c in chronione}
    for root in sorted(roots):
        if _pod(out, root):
            return f"katalog raportu {out} leży w {root} albo pod nim"
    if os.path.lexists(out):
        if not os.path.isdir(out):
            return f"katalog raportu {out} istnieje i nie jest katalogiem"
        if os.listdir(out):
            return f"katalog raportu {out} istnieje i nie jest pusty"
    return None


def _utworz_katalog(path):
    """Katalog (z rodzicami); istniejący katalog zostaje bez zmian."""
    os.makedirs(path, exist_ok=True)


def _usun_pusty(path):
    """Sprzątanie po odmowie po utworzeniu: wyłącznie pusty katalog, który drzwi same założyły."""
    os.rmdir(path)


def _zapisz_plik(cel, kawalki):
    """Zapis `kawalki` (iterowalne bajty) do NOWEGO pliku `cel` przez `cel.tmp` + `os.rename`.
    Plik tymczasowy powstaje wyłącznie jako nowy (`xb`); błąd w trakcie usuwa go i leci dalej.
    Publikacja przez `os.rename`, nie `os.replace`: sprawdzenie `lexists` w `Raport._cel` jest
    wcześniej niż publikacja, a w tym oknie cel może zapisać drugi proces - `os.rename` na Windows
    rzuca wtedy `FileExistsError` zamiast nadpisać (poza Windows `rename` zastępuje cel)."""
    tmp = cel + ".tmp"
    fh = open(tmp, "xb")              # istniejący `.tmp` = FileExistsError; cudzego pliku nie usuwamy
    try:
        with fh:
            for kawalek in kawalki:
                fh.write(kawalek)
            fh.flush()
            os.fsync(fh.fileno())
    except BaseException:
        os.remove(tmp)
        raise
    try:
        os.rename(tmp, cel)
    except FileExistsError:
        os.remove(tmp)
        raise RaportOdmowa(f"plik raportu {cel} powstał w trakcie zapisu - drzwi nie nadpisują") from None


def _usun_plik(path):
    """Usunięcie pliku, który drzwi same przed chwilą zapisały (kopia odrzucona po weryfikacji)."""
    os.remove(path)


def _czytaj(path):
    with open(path, "rb") as fh:
        for kawalek in iter(lambda: fh.read(_CHUNK), b""):
            yield kawalek


def otworz(out, wejscia, *, chronione):
    """Katalog raportu gotowy do zapisu → `Raport`; odmowa → `RaportOdmowa` bez śladu na dysku.

    Położenie sprawdzane jest dwa razy: przed utworzeniem (odmowa nic nie zakłada) i po nim, bo
    `realpath` nieistniejącej ścieżki rozwiązuje dowiązania tylko w istniejącym przedrostku.
    Katalog założony przez drzwi i odrzucony w drugim sprawdzeniu jest usuwany (jest pusty)."""
    wejscia = [os.path.abspath(f) for f in wejscia]
    powod = odmowa_katalogu(out, wejscia, chronione=chronione)
    if powod:
        raise RaportOdmowa(powod)
    nowy = not os.path.lexists(out)
    _utworz_katalog(out)
    powod = odmowa_katalogu(out, wejscia, chronione=chronione)
    if powod:
        if nowy:
            _usun_pusty(out)
        raise RaportOdmowa(powod)
    return Raport(os.path.abspath(out), wejscia)


class Raport:
    """Otwarty katalog raportu. Tworzony wyłącznie przez `otworz`; każda ścieżka zapisu przechodzi
    przez `_cel`."""

    def __init__(self, katalog, wejscia):
        self.katalog = katalog
        self._wejscia = {os.path.normcase(f): f for f in wejscia}

    def _cel(self, nazwa):
        """Ścieżka bezwzględna pliku `nazwa` pod katalogiem raportu; rodzic tworzony w razie potrzeby.

        Odmowa: nazwa pusta, bezwzględna, z dyskiem (`C:x`), z `:` (strumień NTFS), z członem `..`
        albo pustym; katalog docelowy, który po rozwiązaniu dowiązań wychodzi poza raport; plik,
        który już istnieje."""
        if not isinstance(nazwa, str) or not nazwa.strip():
            raise RaportOdmowa(f"nazwa pliku raportu {nazwa!r} jest pusta")
        if os.path.isabs(nazwa) or os.path.splitdrive(nazwa)[0] or ":" in nazwa:
            raise RaportOdmowa(f"nazwa pliku raportu {nazwa!r} nie jest względna")
        czlony = nazwa.replace("\\", "/").split("/")
        if any(c in ("", ".", "..") for c in czlony):
            raise RaportOdmowa(f"nazwa pliku raportu {nazwa!r} ma człon pusty, '.' albo '..'")
        cel = os.path.join(self.katalog, *czlony)
        rodzic = os.path.dirname(cel)
        if not _wewnatrz(rodzic, self.katalog) or not _wewnatrz(cel, self.katalog):
            raise RaportOdmowa(f"{nazwa!r} wychodzi poza katalog raportu {self.katalog}")
        _utworz_katalog(rodzic)
        if not _wewnatrz(rodzic, self.katalog):      # dowiązanie w istniejącym przedrostku
            raise RaportOdmowa(f"{nazwa!r} wychodzi poza katalog raportu {self.katalog}")
        if os.path.lexists(cel) or os.path.lexists(cel + ".tmp"):
            raise RaportOdmowa(f"plik raportu {cel} już istnieje - drzwi nie nadpisują")
        return cel

    def zapisz_bajty(self, nazwa, dane):
        """Bajty `dane` do NOWEGO pliku `nazwa` (względnej) w raporcie. Zwraca ścieżkę."""
        cel = self._cel(nazwa)
        _zapisz_plik(cel, [bytes(dane)])
        return cel

    def zapisz_tekst(self, nazwa, tekst):
        """Tekst w UTF-8 do NOWEGO pliku `nazwa` (względnej) w raporcie. Zwraca ścieżkę."""
        return self.zapisz_bajty(nazwa, tekst.encode("utf-8"))

    def kopia_dla_astap(self, zrodlo):
        """Kopia pliku wejścia do `<raport>/astap/` - ASTAP pisze wyniki obok rozwiązywanego pliku,
        więc dostaje kopię, nigdy oryginał. Źródło musi być zgłoszone w `wejscia` przy `otworz`.
        Ta sama nazwa z dwóch katalogów dostaje sufiks `_2`, `_3`... Zwraca ścieżkę kopii;
        rozmiar kopii inny niż źródła = `OSError` (kopia, której nie można ufać, nie zostaje)."""
        klucz = os.path.normcase(os.path.abspath(zrodlo))
        if klucz not in self._wejscia:
            raise RaportOdmowa(f"{zrodlo} nie jest wejściem raportu - drzwi kopiują tylko wejścia")
        zrodlo = self._wejscia[klucz]
        stem, suffix = os.path.splitext(os.path.basename(zrodlo))
        nazwa, n = f"{stem}{suffix}", 1
        while os.path.lexists(os.path.join(self.katalog, ASTAP_DIR, nazwa)):
            n += 1
            nazwa = f"{stem}_{n}{suffix}"
        cel = self._cel(f"{ASTAP_DIR}/{nazwa}")
        _zapisz_plik(cel, _czytaj(zrodlo))
        if os.path.getsize(cel) != os.path.getsize(zrodlo):
            _usun_plik(cel)
            raise OSError(f"kopia {cel} ma inny rozmiar niż {zrodlo}")
        return cel
