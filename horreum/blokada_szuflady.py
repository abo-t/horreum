"""Wyłączność szuflady Zbiorów bazy POZA GUI (AR-322) - blokada `<baza>.szuflada.lock` w formacie `QLockFile`,
Qt-wolna (rdzeń i CLI nie importują Qt).

Szufladę bazy prowadzi jeden wykonawca naraz: okno trzyma `QLockFile` obok bazy (`gui.grid.FramesView._wez_szuflade`),
dokończenie cofnięcia z Porządków ją sprawdza (`gui.app.ObjectAxisView._obcy_wlasciciel_bazy`). CLI zapisu
(`rename --apply/--undo`, `header-fix --apply/--undo`, `object-change`) stawiał i zapisywał przebieg bez niej, a okno
podejmowało taki przebieg między plikami (zmierzone: po pliku 1 z 3 szuflada drugiego połączenia widzi go jako
„przerwany”, n = 2) i jego „Zatwierdź” ścigało się z CLI. Ten moduł zakłada TEN SAM plik, którego okno nie odróżni
od blokady innego okna.

FORMAT (zmierzony na Qt 6.9.2, bajt w bajt): `PID\\nNAZWA_OBRAZU\\nHOST\\nMACHINE_ID\\n\\n` - nazwa obrazu procesu bez
rozszerzenia (`GetModuleFileNameExW`, jak Qt - nie `applicationName`), host z `COMPUTERNAME`, `MachineGuid` z rejestru,
pusta linia identyfikatora rozruchu (na Windows pusty). Qt porównuje nazwę obrazu z żywym procesem o tym PID-zie
(ponowne użycie PID-u): obca nazwa przy nietrzymanym pliku = blokada martwa.

UCHWYT jak `QLockFilePrivate::tryLock_sys`: `CreateFileW(GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ, CREATE_NEW)`.
Trzymanego pliku nikt nie nadpisze ani nie usunie (WinError 32 - zmierzone dla trzymacza Qt i tego modułu), a jego
treść każdy przeczyta (PID do zdania odmowy). `FILE_FLAG_DELETE_ON_CLOSE` odpada: plik z nim jest nieczytelny dla
otwierających bez `FILE_SHARE_DELETE` (Qt, CPython) - `getLockInfo` oddaje `(0, '', '')`, a okno uznałoby bazę za wolną.

PRZEJĘCIE MARTWEJ: plik istnieje → `os.remove`: przeszło (nikt nie trzyma - proces padł) albo `FileNotFoundError` (ktoś
sprzątnął pierwszy) → JEDNA ponowna próba założenia; usunięcie odmówione (trzymana) albo druga porażka (przegrany
wyścig) → `SzufladaZajeta` z polami z treści pliku. Bez `.rmlock` Qt: usunąć da się wyłącznie plik nietrzymany, więc
dwaj sprzątający nie skasują świeżej blokady trzeciego.

ZWOLNIENIE: zamknięcie uchwytu, potem `os.remove`; `FileNotFoundError` albo WinError 32 = blokadę przejął ktoś po
zamknięciu (legalne - przejąć da się tylko plik nietrzymany), więc cisza. Proces zabity w biegu zostawia plik
NIETRZYMANY: okno (PID martwy) i następne polecenie (usunięcie przechodzi) przejmują go od razu.

OGRANICZENIA (nazwane, nieobsługiwane topologie): blokada jest per PLIK BAZY - dwie bazy nad jednym archiwum się nie
wykluczają (jedna baza = jedno archiwum); blokada z INNEGO hosta przez SMB - Qt nie sprawdzi PID-u obcej maszyny, a przy
`setStaleLockTime(0)` porzucona stoi do ręcznego usunięcia (SQLite z dwóch hostów przez SMB i tak nie jest obsługiwane);
tożsamość blokady to NAPIS ścieżki bazy z połączenia - ta sama baza podana inną nazwą (8.3 `PROGRA~1`, junction) daje
inny plik blokady, tak jak dwa okna otwarte różnymi nazwami. Poza Windows `OSError` (jak `writeback._exclusive`).

DRZWI ZAPISU (bramka `tests/test_writeback_safety.py`, `DOORS`): moduł mutuje WYŁĄCZNIE plik `sciezka(baza)` - stan
obok bazy, nie dane użytkownika - w dwóch funkcjach: `_zaloz` (`CreateFileW`) i `_usun` (`os.remove`)."""
import ctypes
import os
import sys
import time

from .item_reasons import blad_windows

PRZYROSTEK = ".szuflada.lock"
_ISTNIEJE = (80, 183)                  # ERROR_FILE_EXISTS, ERROR_ALREADY_EXISTS (jak Qt: blokada zajęta)
_ZAJETY = 32                           # ERROR_SHARING_VIOLATION - plik trzymany bez FILE_SHARE_DELETE
_ODMOWA = 5                            # ERROR_ACCESS_DENIED - bez pliku: usuwany właśnie przez kogoś (Qt)


def sciezka(db_path):
    """Plik blokady szuflady bazy - ten sam, który zakłada okno (`QLockFile(<baza> + ".szuflada.lock")`)."""
    return db_path + PRZYROSTEK


class SzufladaZajeta(Exception):
    """Szufladę bazy prowadzi inny proces: pola z treści jego blokady (`None`, gdy nieczytelna)."""

    def __init__(self, plik, pid, program, host):
        super().__init__(f"blokada {plik} trzymana (PID {pid}, program {program}, host {host})")
        self.plik, self.pid, self.program, self.host = plik, pid, program, host


class Blokada:
    """Trzymana wyłączność (`wez`); `zwolnij` - raz, kolejne wołania nic nie robią. Baza w pamięci (`:memory:`,
    pusta ścieżka) ma jedno połączenie - blokada pusta, jak w oknie."""

    def __init__(self, plik, uchwyt):
        self.plik, self._uchwyt = plik, uchwyt

    def zwolnij(self):
        if self._uchwyt is None:
            return
        uchwyt, self._uchwyt = self._uchwyt, None
        _kernel32().CloseHandle(uchwyt)
        try:
            _usun(self.plik)
        except FileNotFoundError:
            pass                       # przejęta po zamknięciu i już zwolniona - nie nasza
        except PermissionError as exc:
            if getattr(exc, "winerror", None) != _ZAJETY:
                raise                  # WinError 32: przejęta po zamknięciu - trzyma ją ktoś inny


def wez(db_path):
    """Weź wyłączność szuflady bazy `db_path` → `Blokada`. Zajęta → `SzufladaZajeta`; pliku blokady nie da się
    założyć (odmowa w katalogu bazy, zerwany udział) → `OSError` z kodem i ścieżką."""
    if not db_path:
        return Blokada(None, None)
    plik = sciezka(db_path)
    tresc = _tresc()
    for proba in (1, 2):
        uchwyt = _zaloz(plik, tresc)
        if uchwyt is not None:
            return Blokada(plik, uchwyt)
        if proba == 2:
            break
        try:
            _usun(plik)                # martwa: nikt jej nie trzyma
        except FileNotFoundError:
            pass                       # ktoś sprzątnął pierwszy - ta sama ponowna próba
        except PermissionError:
            break                      # trzymana (WinError 32) - żywy właściciel
    # Zwycięzca wyścigu zakłada plik i dopiero potem pisze treść (jak Qt): przegrany, który czyta w tym
    # oknie, widzi plik pusty - krótkie ponowienie odczytu (≤ ~0,1 s), żeby zdanie odmowy miało PID.
    for _ in range(20):
        pola = _czytaj(plik)
        if pola[0] is not None:
            break
        time.sleep(0.005)
    raise SzufladaZajeta(plik, *pola)


def _kernel32():
    if sys.platform != "win32":
        raise OSError("blokada szuflady wymaga Windows (CreateFileW, jak QLockFile)")
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    k32.WriteFile.argtypes = (wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                              ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p)
    k32.FlushFileBuffers.argtypes = (wintypes.HANDLE,)
    k32.CloseHandle.argtypes = (wintypes.HANDLE,)
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.K32GetModuleFileNameExW.argtypes = (wintypes.HANDLE, wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD)
    return k32


def _zaloz(plik, tresc):
    """Uchwyt nowej blokady z treścią albo None - plik już jest (albo właśnie znika). Inny błąd → `OSError`.

    Plik założony, a uchwyt nieoddany (błąd zapisu treści albo przerwanie, np. `KeyboardInterrupt`, w sprawdzeniu
    uchwytu albo w zapisie): zamknięcie uchwytu, usunięcie pliku i rzut dalej. Pusty plik zostawiony po przerwaniu
    stałby w oknie (`setStaleLockTime(0)`: bez PID-u nie uzna go za martwy) do ręcznego usunięcia. Sprzątanie
    tylko przy prawidłowym uchwycie - plik bez naszego uchwytu (już był, właśnie znika) nie jest nasz."""
    from ctypes import wintypes
    k32 = _kernel32()
    zly = (None, wintypes.HANDLE(-1).value)
    uchwyt = None
    try:
        uchwyt = k32.CreateFileW(plik, 0x80000000 | 0x40000000, 0x1, None, 1, 0x80, None)
        if uchwyt in zly:
            kod = ctypes.get_last_error()
            if kod in _ISTNIEJE or kod == _ZAJETY or (kod == _ODMOWA and not os.path.exists(plik)):
                return None
            raise blad_windows(kod, plik)
        zapisane = wintypes.DWORD()
        bufor = ctypes.create_string_buffer(tresc, len(tresc))
        if not (k32.WriteFile(uchwyt, bufor, len(tresc), ctypes.byref(zapisane), None)
                and zapisane.value == len(tresc) and k32.FlushFileBuffers(uchwyt)):
            raise blad_windows(ctypes.get_last_error(), plik)
    except BaseException:
        if uchwyt not in zly:
            k32.CloseHandle(uchwyt)
            _usun(plik)
        raise
    return uchwyt


def _usun(plik):
    os.remove(plik)


def _tresc():
    """Treść blokady bajt w bajt jak `QLockFilePrivate::lockFileContents` (Qt 6.9.2, Windows)."""
    return (f"{os.getpid()}\n{_nazwa_obrazu()}\n{os.environ.get('COMPUTERNAME', '')}\n"
            f"{_id_maszyny()}\n\n").encode("utf-8")


def _nazwa_obrazu():
    k32 = _kernel32()
    bufor = ctypes.create_unicode_buffer(32768)
    n = k32.K32GetModuleFileNameExW(k32.GetCurrentProcess(), None, bufor, len(bufor))
    return os.path.splitext(os.path.basename(bufor.value[:n]))[0]


def _id_maszyny():
    """`MachineGuid` (to samo co `QSysInfo.machineUniqueId` na Windows - zmierzone równością bajtów) albo ""."""
    import winreg
    try:
        klucz = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0,
                               winreg.KEY_READ | winreg.KEY_WOW64_64KEY)
        try:
            return str(winreg.QueryValueEx(klucz, "MachineGuid")[0])
        finally:
            winreg.CloseKey(klucz)
    except OSError:
        return ""


def _czytaj(plik):
    """`(pid, program, host)` z treści cudzej blokady; nieczytelna albo zniknęła → pola None."""
    try:
        with open(plik, "rb") as fh:
            linie = fh.read().decode("utf-8", "replace").split("\n")
        return int(linie[0]), linie[1] or None, linie[2] or None
    except (OSError, ValueError, IndexError):
        return None, None, None
