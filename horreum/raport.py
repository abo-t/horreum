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

PODMIANA W TRAKCIE (dług `AR-51`, TOCTOU): sprawdzenie ścieżki i zapis to dwie chwile, a między
nimi drugi proces mógłby podmienić `--out`, jego rodzica albo podkatalog raportu na junction do
źródła. Drzwi PRZYPINAJĄ każdy katalog, w którym piszą (`_przypnij`, Windows): uchwyt katalogu
bez `FILE_SHARE_DELETE` blokuje jego usunięcie i zmianę nazwy, a otwarty uchwyt w poddrzewie blokuje
zmianę nazwy każdego przodka (zmierzone 2026-10-05: zmiana nazwy przodka → `ERROR_ACCESS_DENIED`,
samego katalogu → `ERROR_SHARING_VIOLATION`). Uchwyt otwiera sam obiekt (bez podążania za reparse
point); katalog, który jest dowiązaniem albo junction, to odmowa. Ścieżką roboczą raportu jest
ścieżka KOŃCOWA przypiętego uchwytu - bez junction w żadnym członie, więc przodków nie da się też
przepiąć. Podkatalogi raportu powstają po jednym członie i każdy jest przypinany przed zejściem
głębiej. Źródło kopii dla ASTAP otwiera się przed kopiowaniem, a tożsamość pliku `(wolumen,
file ID)` z uchwytu musi być ta sama, co przy `otworz`; liczba skopiowanych bajtów = rozmiar z tego
samego uchwytu. Uchwyty zwalnia `Raport.zamknij` (albo wyjście z `with`).
Poza Windows przypięcia nie ma (brak blokady współdzielenia) - zostają kontrole ścieżek; tożsamość
źródła kopii obowiązuje wszędzie. Wariant pełny - każda operacja względem uchwytu katalogu
(`NtCreateFile` z `RootDirectory`) - nie jest potrzebny, póki przypięcie zamyka okno podmiany.

Ścieżek prywatnych w kodzie nie ma (repo publiczne): korzeń archiwum podaje wołający w `chronione`.
"""
from __future__ import annotations

import os
import stat
import sys
import weakref

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


def _kernel32():
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    k32.GetFinalPathNameByHandleW.restype = wintypes.DWORD
    k32.GetFinalPathNameByHandleW.argtypes = (wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD,
                                              wintypes.DWORD)
    k32.CloseHandle.argtypes = (wintypes.HANDLE,)
    return k32


def _dowiazanie(path):
    """Czy sam obiekt pod `path` (bez podążania) jest dowiązaniem albo junction (reparse point)."""
    st = os.lstat(path)
    return bool(getattr(st, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
                if sys.platform == "win32" else stat.S_ISLNK(st.st_mode))


def _bez_przedrostka(path):
    """Ścieżka końcowa uchwytu bez przedrostka `\\\\?\\` (`\\\\?\\UNC\\x` → `\\\\x`)."""
    if path.startswith("\\\\?\\UNC\\"):
        return "\\\\" + path[8:]
    return path[4:] if path.startswith("\\\\?\\") else path


def _przypnij(path, powod):
    """Przypięcie katalogu `path` (AR-51) → `(uchwyt, ścieżka końcowa)`; dowiązanie albo junction =
    `RaportOdmowa(powod)` bez uchwytu.

    Windows: `CreateFileW` z prawem listowania (uchwyt z samym odczytem atrybutów nie uczestniczy
    w sprawdzaniu współdzielenia - zmierzone: zmiana nazwy przechodziła), współdzielenie odczytu
    i zapisu BEZ usuwania, `FILE_FLAG_OPEN_REPARSE_POINT` (otwiera sam obiekt, nie cel junction).
    Ścieżka końcowa = `GetFinalPathNameByHandleW` przypiętego uchwytu. Poza Windows uchwytu nie ma
    (None), ścieżka końcowa = `realpath`."""
    if sys.platform != "win32":
        if _dowiazanie(path):
            raise RaportOdmowa(powod)
        return None, os.path.realpath(path)
    import ctypes
    k32 = _kernel32()
    list_directory, share_read_write, open_existing = 0x1, 0x3, 3
    backup_semantics, open_reparse_point = 0x02000000, 0x00200000
    uchwyt = k32.CreateFileW(path, list_directory, share_read_write, None, open_existing,
                             backup_semantics | open_reparse_point, None)
    if uchwyt in (None, ctypes.c_void_p(-1).value):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if _dowiazanie(path):
            raise RaportOdmowa(powod)
        buf = ctypes.create_unicode_buffer(32768)
        if not k32.GetFinalPathNameByHandleW(uchwyt, buf, len(buf), 0):
            raise ctypes.WinError(ctypes.get_last_error())
    except BaseException:
        k32.CloseHandle(uchwyt)
        raise
    return uchwyt, _bez_przedrostka(buf.value)


def _zwolnij(uchwyty):
    """Zamknięcie uchwytów przypięcia (wartości słownika albo pojedynczy uchwyt); None pomijane."""
    for uchwyt in (uchwyty.values() if isinstance(uchwyty, dict) else [uchwyty]):
        if uchwyt is not None:
            _kernel32().CloseHandle(uchwyt)
    if isinstance(uchwyty, dict):
        uchwyty.clear()


def _tozsamosc(st):
    """Tożsamość pliku z `os.stat`/`os.fstat`: (wolumen, file ID) - nie ścieżka."""
    return st.st_dev, st.st_ino


def _tozsamosc_lub_none(path):
    """Tożsamość wejścia przy `otworz`; nieczytelne (zniknęło po wylistowaniu, ACL) = None - raport
    i tak powstaje (klatka dostanie status błędu u wołającego), a kopia dla ASTAP takiego wejścia
    odmówi, bo nie ma z czym porównać uchwytu."""
    try:
        return _tozsamosc(os.stat(path))
    except OSError:
        return None


def otworz(out, wejscia, *, chronione):
    """Katalog raportu gotowy do zapisu → `Raport`; odmowa → `RaportOdmowa` bez śladu na dysku.

    Położenie sprawdzane jest dwa razy: przed utworzeniem (odmowa nic nie zakłada) i po
    przypięciu, na ścieżce końcowej uchwytu - tam, gdzie raport będzie pisany. Katalog założony
    przez drzwi i odrzucony w drugim sprawdzeniu jest usuwany (jest pusty). Tożsamość każdego
    wejścia (`_tozsamosc`) zapisywana jest tu - kopia dla ASTAP porównuje z nią otwarty plik."""
    wejscia = [os.path.abspath(f) for f in wejscia]
    powod = odmowa_katalogu(out, wejscia, chronione=chronione)
    if powod:
        raise RaportOdmowa(powod)
    tozsamosc = {os.path.normcase(f): _tozsamosc_lub_none(f) for f in wejscia}
    nowy = not os.path.lexists(out)
    _utworz_katalog(out)
    uchwyt = None
    try:
        uchwyt, katalog = _przypnij(out, f"katalog raportu {out} jest dowiązaniem albo junction")
        powod = odmowa_katalogu(katalog, wejscia, chronione=chronione)
        if powod:
            raise RaportOdmowa(powod)
    except RaportOdmowa:
        _zwolnij(uchwyt)
        if nowy:
            _usun_pusty(out)
        raise
    except BaseException:
        _zwolnij(uchwyt)
        raise
    return Raport(katalog, wejscia, tozsamosc, uchwyt)


class Raport:
    """Otwarty katalog raportu. Tworzony wyłącznie przez `otworz`; każda ścieżka zapisu przechodzi
    przez `_cel`. `katalog` = ścieżka końcowa przypiętego katalogu. Uchwyty przypięcia zwalnia
    `zamknij` (także wyjście z `with` i zbieranie obiektu)."""

    def __init__(self, katalog, wejscia, tozsamosc, uchwyt):
        self.katalog = katalog
        self._wejscia = {os.path.normcase(f): f for f in wejscia}
        self._tozsamosc = tozsamosc
        self._uchwyty = {os.path.normcase(katalog): uchwyt}
        self._zamknij = weakref.finalize(self, _zwolnij, self._uchwyty)

    def zamknij(self):
        """Zwolnienie przypięć; dalszy zapis przez ten obiekt nie jest już chroniony przed podmianą."""
        self._zamknij()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.zamknij()

    def _podkatalog(self, rodzic, czlon, nazwa):
        """Podkatalog `czlon` przypiętego katalogu `rodzic`: założony (jeden człon), przypięty
        i sprawdzony - ścieżka końcowa uchwytu musi być dokładnie `rodzic/czlon`, więc ani
        junction, ani podmiana między założeniem a przypięciem nie wyprowadzają poza raport."""
        sciezka = os.path.join(rodzic, czlon)
        klucz = os.path.normcase(sciezka)
        if klucz not in self._uchwyty:
            powod = f"{nazwa!r} wychodzi poza katalog raportu {self.katalog}"
            if os.path.lexists(sciezka) and _dowiazanie(sciezka):
                raise RaportOdmowa(powod)
            try:
                _utworz_katalog(sciezka)
            except (FileExistsError, NotADirectoryError):     # obcy plik w miejscu podkatalogu
                raise RaportOdmowa(f"{nazwa!r}: {sciezka} istnieje i nie jest katalogiem") from None
            uchwyt, koncowa = _przypnij(sciezka, powod)
            if os.path.normcase(koncowa) != klucz:
                _zwolnij(uchwyt)
                raise RaportOdmowa(powod)
            self._uchwyty[klucz] = uchwyt
        return sciezka

    def _cel(self, nazwa):
        """Ścieżka bezwzględna pliku `nazwa` pod katalogiem raportu; podkatalogi zakładane
        i przypinane po jednym członie (`_podkatalog`).

        Odmowa: nazwa pusta, bezwzględna, z dyskiem (`C:x`), z `:` (strumień NTFS), z członem `..`
        albo pustym; człon katalogu, który jest dowiązaniem albo junction; plik, który już istnieje."""
        if not isinstance(nazwa, str) or not nazwa.strip():
            raise RaportOdmowa(f"nazwa pliku raportu {nazwa!r} jest pusta")
        if os.path.isabs(nazwa) or os.path.splitdrive(nazwa)[0] or ":" in nazwa:
            raise RaportOdmowa(f"nazwa pliku raportu {nazwa!r} nie jest względna")
        czlony = nazwa.replace("\\", "/").split("/")
        if any(c in ("", ".", "..") for c in czlony):
            raise RaportOdmowa(f"nazwa pliku raportu {nazwa!r} ma człon pusty, '.' albo '..'")
        rodzic = self.katalog
        for czlon in czlony[:-1]:
            rodzic = self._podkatalog(rodzic, czlon, nazwa)
        cel = os.path.join(rodzic, czlony[-1])
        if not _wewnatrz(cel, self.katalog):
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
        Ta sama nazwa z dwóch katalogów dostaje sufiks `_2`, `_3`... Zwraca ścieżkę kopii.

        Źródło jest otwierane PRZED kopiowaniem, a kopia czyta z tego samego uchwytu: tożsamość
        `(wolumen, file ID)` uchwytu inna niż przy `otworz` (junction w ścieżce podmieniony
        w międzyczasie) = `RaportOdmowa`, nic nie zapisane; liczba skopiowanych bajtów inna niż
        rozmiar z uchwytu = `OSError` (kopia, której nie można ufać, nie zostaje)."""
        klucz = os.path.normcase(os.path.abspath(zrodlo))
        if klucz not in self._wejscia:
            raise RaportOdmowa(f"{zrodlo} nie jest wejściem raportu - drzwi kopiują tylko wejścia")
        zrodlo = self._wejscia[klucz]
        stem, suffix = os.path.splitext(os.path.basename(zrodlo))
        nazwa, n = f"{stem}{suffix}", 1
        while os.path.lexists(os.path.join(self.katalog, ASTAP_DIR, nazwa)):
            n += 1
            nazwa = f"{stem}_{n}{suffix}"
        with open(zrodlo, "rb") as fh:
            st = os.fstat(fh.fileno())
            if self._tozsamosc[klucz] is None or _tozsamosc(st) != self._tozsamosc[klucz]:
                raise RaportOdmowa(f"{zrodlo} to inny plik niż przy otwarciu raportu - kopia odrzucona")
            cel = self._cel(f"{ASTAP_DIR}/{nazwa}")
            skopiowane = []

            def kawalki():
                for kawalek in iter(lambda: fh.read(_CHUNK), b""):
                    skopiowane.append(len(kawalek))
                    yield kawalek

            _zapisz_plik(cel, kawalki())
        if sum(skopiowane) != st.st_size:
            _usun_plik(cel)
            raise OSError(f"kopia {cel} ma {sum(skopiowane)} B, a źródło {zrodlo} {st.st_size} B")
        return cel
