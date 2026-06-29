"""Trwały identyfikator wolumenu (numer seryjny) — MINIMALNY wycinek PLAN_skan §7.5 pod bramę
przyrostową (`scan.py` §3.B). Read-only OS call, ZERO zapisu, zero zależności poza stdlib+ctypes.

Po co: brama przyrostowa opiera tożsamość lokalizacji na `(volume, path)`; `volume` MUSI być stabilny
między sesjami/remountami, a litera dysku jest EFEMERYCZNA (`location.drive_letter` = „NIE tożsamość").
Numer seryjny woluminu (NTFS/FAT) jest stały do reformatu — wystarcza, by „ten sam dysk pod INNĄ
literą" nie dał fałszywego TRAFIENIA (= pominięcia pliku nigdy nieskanowanego, złamanie inwariantu D1).

Nieustalony serial (nie-Windows, błąd API, ścieżka bez woluminu) → `None` → wołający podstawia
placeholder `'?'` → brama OFF → PEŁNY skan (zero fałszywych pominięć; bezpieczny fallback)."""
import sys
from pathlib import Path


def volume_serial(path):
    """Numer seryjny woluminu, na którym leży `path`, jako 8-znakowy hex (np. `'A1B2C3D4'`), albo
    `None` gdy nie da się ustalić (nie-Windows, błąd API, ścieżka bez litery). Hex to stabilny,
    porównywalny string do kolumny `location.volume`. Nigdy nie rzuca — fallback `None` jest częścią
    kontraktu bramy (`'?'` → pełny skan)."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        drive = Path(path).drive                  # 'R:' (litera) lub '\\\\host\\share' (UNC)
        if not drive:
            return None
        root = drive + "\\"                        # GetVolumeInformationW wymaga roota z backslashem
        serial = ctypes.c_ulong(0)
        ok = ctypes.windll.kernel32.GetVolumeInformationW(
            ctypes.c_wchar_p(root),
            None, 0,                               # bufor nazwy woluminu — niepotrzebny
            ctypes.byref(serial),
            None, None,                            # max długość komponentu, flagi FS — niepotrzebne
            None, 0,                               # bufor nazwy systemu plików — niepotrzebny
        )
        if not ok:
            return None
        return f"{serial.value:08X}"
    except Exception:
        return None
