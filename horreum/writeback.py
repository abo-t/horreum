"""DRUGA KLINGA — jedyny obramkowany dom MUTACJI PLIKÓW (KROK 4 scalenia, brief PLAN_gui_writeback).

Odpowiednik `repo.py` dla plików: writeback nagłówków FITS to JEDYNY sankcjonowany zapis na dysk
usera (poza nim pliki = zimny magazyn, `safety.py`). Statyczny meta-tripwir AST
(`tests/test_writeback_safety.py`) pilnuje, że `os.replace`/`writeto`/`tempfile`/`os.remove` żyją
WYŁĄCZNIE tutaj (wzorzec `mover.py`/`eraser.py` Custosa, przełożony z zakazu DML poza `repo.py`).

Dwie warstwy:
1. WRITER (port dawcy `fits_io.write_changes`/`write_full_header`): atomowy zapis nagłówka —
   plik tymczasowy w tym samym katalogu, przygotowany pod blokadą zapisu innych, + podmiana
   systemowa z kopią pliku wypartego i jego rewalidacją (sekcja „PODMIANA SYSTEMOWA", AR-18). Kontrola
   `header_hash` PRZED zapisem (niezgodny → 'blocked', NIE pisze). Hash PO zapisie liczony z
   ZAPISANEGO pliku przez `scan.read_fits_meta` (astropy normalizuje formatowanie przy `writeto`
   — hash „z pamięci" nie pasowałby do pliku; brief T3, lekcja dawcy `fits_io.py:289`).
   Treść łaty przechodzi PRZED zapisem reguły karty FITS 4.0 (`card_violation` - jeden właściciel
   dla obu formatów, sekcja „REGUŁY KARTY"); łamiąca → 'blocked', plik nietknięty. Weryfikacja PO
   `os.replace`, która padnie, daje 'failed' Z `backup_text` - plik jest już zmieniony, więc undo
   nie może stracić materiału (`_after_replace`).
   Od P6c writer ma DWA formaty: FITS (astropy) i XISF (łata bajtowa — sekcja „PISARZ XISF").
   Dyspozycja po rozszerzeniu w `write_changes`/`write_full_header`/`_post_hash`, więc
   ORKIESTRACJA (niżej) o formacie nie wie — commit i undo są dla obu identyczne.
   Od O5 (2026-09-26) writer ma DRUGĄ DROGĘ: ZAPIS W MIEJSCU (`write_changes_inplace`, sekcja
   „ZAPIS W MIEJSCU") - podmiana samego regionu nagłówka na uchwycie z BLOKADĄ zapisu innych
   (`_exclusive`: `CreateFileW` z `FILE_SHARE_READ`), bez pliku tymczasowego, z backupem PRZED
   zapisem i weryfikacją po nim. Commit wybiera ją jawnie (`commit(inplace=True)`), undo - zawsze,
   gdy przywracany nagłówek mieści się w tych samych bajtach. Rozdarty nagłówek naprawia
   `restore_region`/`recover_torn` z backupu regionu, bez parsowania.
   BACKUP (obie drogi, od 2026-09-26) = `RegionBackup`: surowy region nagłówka + offset, rozmiar,
   `st_ino`, próbki poza regionem, hash - w kolumnie tekstowej `header_backups.header_text`.
2. ORKIESTRACJA (`commit`/`undo`): grupuje `pending_changes` po LOCATION, per plik zapisuje i
   RE-SYNCUJE bazę przez `scan.ingest_record(actor="user:local")` — REUŻYWA znanej-ścieżki skanu
   (SPOT, brief §3/R#2): `refresh_location` odświeża fakty kopii + zeznanie + WYMIANĘ `cards` +
   przelicza `frame.camera_id`/`kind` (`event(frame.rederived)`). Bespoke writer POMINĄŁBY rederive
   → config na stęchłej kamerze. KAŻDY re-sync emituje eventy (fakt domenowy = mutacja pliku);
   staging (backup/status/commit) jest transient, BEZ eventu (brief §3/R#1).

Kolejność BAZA→PLIK→BAZA: backup undo PIERWSZY (w obu drogach - przed `os.replace` i przed
pierwszym bajtem zapisu w miejscu; Z3 2026-09-26, dawniej backup szedł PO podmianie), potem plik,
potem re-sync; crash między plikiem a re-synciem → plik zmieniony, DB stęchłe, kotwicą naprawy jest
RE-SKAN (`header_hash` mismatch → refresh), a dla zapisu w miejscu przerwanego w połowie - odzysk
z backupu regionu. Zapis w miejscu IZOLUJE lokację od skanu i od innych mutacji aż do udanej
kontroli danych i re-syncu (faza `synced`, `repo.INPLACE_ISOLATING_PHASES`); porażka re-syncu
zostawia ją izolowaną, a drogą naprawy jest dokończenie (`finish_inplace`), nie re-skan - chyba że
kontrola danych nie przechodzi: wtedy droga powrotu (`recover_torn` dla `written`) przywraca stary
nagłówek w miejscu i zwalnia lokację do pełnego skanu.
Utrwalanie per plik (funkcje stagingu `repo` commitują od razu),
więc anulowanie na granicy pliku jest bezpieczne: pliki już zapisane zostają 'applied', reszta
'pending' (wznawialne).
"""

from __future__ import annotations

import base64
import contextlib
import ctypes
import dataclasses
import hashlib
import json
import os
import re
import sqlite3
import struct
import sys
import tempfile
import time
import warnings
import zlib
import xml.etree.ElementTree as ET
from collections.abc import Callable

from astropy.io import fits

from . import exif, hashing, repo, scan
from .card_rules import FITS_RECORD as _FITS_RECORD
from .resolve.paths import path_key   # ścieżka FIZYCZNA (bez wielkości liter) - jak planer i straż
from .object_change import ZdanieRdzenia   # ostrzeżenie gestu z kodem dla okna (AR-138)
from .item_reasons import (ITEM_REASON_CODES,   # powód z kodem (AR-141, AR-148)
                           OdmowaZPowodem, PowodPozycji, dopisz_z_koperta, powod_wyjatku, z_bazy)
# Błędy systemu klasą - właściciel `item_reasons` (AR-168, AR-184); nazwy modułu zostają dla miejsc pisarza.
from .item_reasons import (blad_systemu as _blad_systemu, proza_z_diagnoza as _proza_z_diagnoza,
                           szczegoly_systemu as _szczegoly_systemu)
# Błąd Windows z kodem i ścieżką - jedna konstrukcja u właściciela (AR-259); nazwa modułu zostaje.
from .item_reasons import blad_windows as _blad_windows
from .card_rules import FITS_STRING_MAX, card_violation  # noqa: F401 - re-eksport („REGUŁY KARTY")

# ============================================================ WRITER (port dawcy fits_io)


@dataclasses.dataclass(frozen=True)
class WriteOp:
    """Operacja zapisu karty. `value` jako string + `value_type` (jak w `pending_changes`)."""
    keyword: str
    op: str  # 'set' | 'add'
    value: object
    value_type: str
    idx: int | None = None
    comment: str | None = None


@dataclasses.dataclass(frozen=True)
class WriteResult:
    """Wynik jednego zapisu. `backup_text is not None` ⇔ plik na dysku JEST PODMIENIONY: przy
    'applied' zawsze, a przy 'failed' wtedy, gdy padła weryfikacja PO `os.replace` - bajty już
    leżą na dysku, więc wołający musi dostać materiał do cofnięcia, inaczej undo traci go na zawsze.
    `post_hash` przy takim 'failed' to hash nagłówka, który pisarz ZAPISAŁ (nie odczytał) - kotwica
    undo przepuści cofnięcie tylko wtedy, gdy na dysku leży dokładnie to, co zapisaliśmy.
    'blocked' i 'failed' sprzed podmiany mają oba pola `None` i plik bajtowo nietknięty.

    `in_place=True` = droga ZAPISU W MIEJSCU (sekcja „ZAPIS W MIEJSCU"): plik ma tę samą tożsamość
    (`st_ino`) i te same bajty danych, a backup (przy commicie) powstał PRZED zapisem - wołający go
    już NIE wstawia. Przy 'failed' w tej drodze `backup_text is not None` znaczy „backup leży
    w bazie, a zapis mógł ruszyć bajty".

    `byte_exact` (przywrócenie z backupu, AR-19): `True` = cały plik ma sha1 sprzed commitu, `None` =
    region nagłówka przywrócony bajt w bajt, a całego pliku nie było z czym porównać (backup bez
    sha1 pliku), `False` = cofnięcie SEMANTYCZNE (nagłówek odtworzony z treści, bajty pliku inne niż
    przed commitem). Przy zapisie zmian zawsze `None`.

    `code` = stan, który powierzchnia ROZPOZNAJE (`CODE_*`), obok zdania dla człowieka w `reason`;
    przechodzi do `FileResult.code`. `None` = powód bez kodu."""
    status: str            # 'applied' | 'blocked' | 'failed'
    reason: str | None
    post_hash: str | None  # header_hash PO zapisie (z ZAPISANEGO pliku) — kontrola undo + kolejny zapis
    backup_text: str | None = None  # pełny nagłówek SPRZED zapisu (undo)
    in_place: bool = False
    byte_exact: bool | None = None
    code: str | None = None


# KODY POWODÓW, które powierzchnie rozpoznają (AR-121 (4)) - zdanie w `reason` jest dla człowieka
# i może się zmienić, kod nie. `CODE_CHANGED_SINCE_SCAN`: odmowa zapisu karty, bo sha1 całego pliku
# różni się od bazy (drogą wyjścia jest skan w Dostawie). `CODE_INPLACE_FALLBACK`: plik zapisany
# drogą atomową po odmowie zapisu w miejscu (`commit(inplace=True, fallback=True)`) - cały plik
# przepisany; `reason` zaczyna się wtedy od `PREFIKS_DROGI_ATOMOWEJ`.
CODE_CHANGED_SINCE_SCAN = "changed_since_scan"
CODE_INPLACE_FALLBACK = "inplace_fallback"
# `CODE_ZEZNANIE_WSTRZYMANE` (AR-82): plik zapisany (albo przywrócony cofnięciem), a zeznanie klatki
# NIE przyjęło jego nagłówka - głosem klatki mówi inna obecna kopia. Status zapisu 'withheld',
# cofnięcia 'restored' z tym kodem; dokończenie po przejęciu zeznania tej kopii (`repo.withheld_write`).
CODE_ZEZNANIE_WSTRZYMANE = "testimony_withheld"
# `CODE_POWROT_WYPARTEJ` (AR-64, wewnętrzny między pisarzem a orkiestracją): podmiana z zamiarem
# wyparła cudzą wersję - pod ścieżką nasza, cudza pod kopią, backup niepotwierdzony; powrót robi
# automat rekoncyliacji (`_rekoncyliuj_zamiar`), a wynik lokacji niesie jego werdykt.
CODE_POWROT_WYPARTEJ = "displaced_return"
# `CODE_REGION_SPRZED` (AR-169, wewnętrzny między pisarzem a orkiestracją cofnięcia): cofnięcie
# w miejscu zastało region nagłówka już równy stanowi sprzed commitu - o „już cofnięte” rozstrzyga
# orkiestracja dowodem całego pliku i bazy (`_cofnij_lokacje`), nie pisarz.
CODE_REGION_SPRZED = "undo_already_region"
PREFIKS_DROGI_ATOMOWEJ = "droga dotychczasowa"

# Powody-stałe pisarza (AR-148): to samo zdanie w wielu bramkach, z kodem dla okna.
_RAW_READ_ONLY = PowodPozycji("format RAW jest read-only (#2)", "raw_read_only")
# Kontrola `header_hash` mówi prawdą swojej drogi: zapis porównuje z nagłówkiem ze STAGINGU
# (`write_changes`, `_xisf_prepare`, plan zapisu w miejscu), cofnięcie atomowe - z nagłówkiem
# zapisanym przez COMMIT (`write_full_header`: `_plan_przywrocenia`, drogi semantyczne). Zdanie po
# polsku, nazwa kontroli w nawiasie (dawniej goły żargon „header_hash mismatch” w obu).
_HEADER_HASH_MISMATCH = PowodPozycji("nagłówek pliku zmienił się od stagingu (header_hash "
                                     "niezgodny)", "header_hash_mismatch")
_UNDO_HEADER_CHANGED = PowodPozycji("nagłówek pliku zmienił się od commitu (header_hash "
                                    "niezgodny)", "undo_header_changed")

# BŁĘDY SYSTEMU KLASĄ (AR-168): `_blad_systemu`, `_szczegoly_systemu`, `_proza_z_diagnoza` to aliasy
# importu z właściciela `item_reasons` (AR-184 - jedna klasyfikacja dla wszystkich dróg plików).
# W tym module tekst wyjątku staje się powodem WYŁĄCZNIE przez `_blad_systemu` (meta-test
# `tests/test_powody_pisarza.py`).
_BRAK_LOCATION = PowodPozycji("brak location w bazie", "no_location")
_KOPIA_ZNIKNELA = PowodPozycji("kopia zniknęła (present=0)", "copy_gone")


def _brak_operacji(op_id) -> PowodPozycji:
    """Powód gestu izolacji, którego operacji nie ma w dzienniku `inplace_op`."""
    return PowodPozycji(f"brak operacji {op_id}", "no_operation", op_id=op_id)


# ============================================================ REGUŁY KARTY (jeden właściciel)
# Właściciel reguł karty FITS 4.0 to `card_rules` - moduł bez astropy, bo pyta go też czysty silnik
# makr w podglądzie (AR-9). Tu żyje tylko to, co wie wyłącznie pisarz: która operacja ZAKŁADA kartę
# (`_ops_violation`) i czy przełożona karta FITS zachowała zastany komentarz (`_fits_comment_loss`).
# `card_violation` i `FITS_STRING_MAX` zostają nazwami `writeback` (re-eksport) - wołają je
# `gui/app.py` (dialog naprawy nagłówka) i testy pisarza.


def _ops_violation(ops, is_new: Callable[[WriteOp], bool]) -> PowodPozycji | None:
    """Powód pierwszego naruszenia reguł karty w komplecie operacji albo `None` - `PowodPozycji`
    z kodem `card_*` prosto od właściciela reguł (`CardViolation.reason`, AR-158), więc okno mówi
    go w języku UI. Czy operacja ZAKŁADA kartę (`is_new`), wie tylko pisarz danego formatu: FITS
    `set` na nieobecnej karcie dopisuje ją po cichu (astropy), XISF odmawia."""
    for op in ops:
        naruszenie = card_violation(op.keyword, op.value, op.comment, new_card=is_new(op))
        if naruszenie is not None:
            return naruszenie.reason
    return None


def _after_replace(path: str, written_hash: str, backup_text: str,
                   uwaga: str | None = None) -> WriteResult:
    """Weryfikacja PO podmianie - wspólna dla FITS i XISF. Plik JEST już podmieniony, więc KAŻDY
    wynik stąd niesie `backup_text`: 'failed' bez backupu zostawiłby zapisany plik bez drogi powrotu.

    `written_hash` = hash nagłówka, który pisarz ZAPISAŁ (XISF: sha1 złożonego XML-a; FITS: odczyt
    pliku tymczasowego przed podmianą). Odczyt po zapisie (T3) musi dać dokładnie ten hash - te same
    bajty, ta sama formuła. Rozjazd albo nieudany odczyt → 'failed' z `post_hash=written_hash`:
    undo porównuje dysk z tym hashem, więc cofnie wyłącznie plik, na którym leży to, co zapisaliśmy,
    a plik zmieniony w międzyczasie przez kogoś innego zostawi jako 'blocked'. `uwaga` (np. kopia
    pliku wypartego, której nie udało się sprzątnąć) idzie do powodu także przy 'applied'."""
    try:
        post = _post_hash(path)
    except Exception as exc:  # noqa: BLE001 - raport zamiast wyjątku w warstwie zapisu
        blad = _blad_systemu(exc)
        return WriteResult("failed", _dopisz(PowodPozycji(
            f"plik PODMIENIONY, ale odczyt po zapisie padł - {blad}", "verify_read_failed",
            detail=blad), uwaga), written_hash, backup_text)
    if post != written_hash:
        return WriteResult("failed", _dopisz(PowodPozycji(
            "plik PODMIENIONY, ale odczyt po zapisie pokazuje inny nagłówek niż zapisany",
            "verify_mismatch"), uwaga), written_hash, backup_text)
    return WriteResult("applied", uwaga, post, backup_text)


def _dopisz(powod: str | None, dopisek: str | None) -> str | None:
    """`powod; dopisek` z pominięciem pustych. Powód z kodem (`PowodPozycji`) zachowuje kod, a dopisek
    idzie na jego listę uwag (`item_reasons.dopisz`, AR-141); część pusta oddaje drugą bez zmian.
    Dopisek Z KODEM za prozą bez kodu (tekst systemu) - proza w kopercie `prose`, kod dopisku zostaje
    (`item_reasons.dopisz_z_koperta` - ta sama reguła co dopiski klingi)."""
    return dopisz_z_koperta(powod, dopisek)


# ------------------------------------------------ PODMIANA SYSTEMOWA (AR-18)
# Droga atomowa (plik tymczasowy) ma trzy chwile: odczyt i przygotowanie, utrwalenie backupu, podmianę.
# Dawniej każda otwierała plik osobno, bez blokady, a `os.replace` kasował to, co stało pod ścieżką -
# równoległy pisarz (PixInsight, drugi proces, CLI) zmieniający plik między odczytem a podmianą tracił
# zmianę bez śladu, a w XISF ogon z wersji B sklejał się z regionem z wersji A. Teraz:
#   1. ODCZYT I PRZYGOTOWANIE POD BLOKADĄ (`_exclusive`, ta sama co zapis w miejscu): nagłówek, plik
#      tymczasowy z ogonem i region backupu powstają, gdy nikt inny nie otworzy pliku do zapisu, więc
#      wszystkie odczyty widzą tę samą wersję; z uchwytu blokady bierze się ODCISK pliku (`_Odcisk`).
#   2. Backup w bazie - po zwolnieniu blokady (zapis do bazy, nie do pliku).
#   3. PODMIANA SYSTEMOWA Z PEŁNYM BACKUPEM (`ReplaceFileW` z `lpBackupFileName`): plik wyparty nie
#      ginie, tylko trafia pod nazwę kopii obok (`*.horreum-kopia`). System otwiera plik do usunięcia,
#      więc blokada musi zejść przed podmianą - okno między 1 a 3 zamyka REWALIDACJA PO WYPARCIU: kopia
#      ma mieć odcisk z kroku 1 (`st_ino`, rozmiar, `mtime`, region nagłówka, próbki danych). Zgodna →
#      kopia znika. Niezgodna (ktoś zmienił plik w oknie) → wyparta wersja wraca pod ścieżkę, nasza
#      przepada, wynik 'blocked' - zmiana tamtego pisarza nie ginie.
# Błędy podmiany jawnie, bez cichej drogi zapasowej: 1175 (pliku nie da się usunąć) i 1176 (z kopią -
# oba pliki pod swoimi nazwami) zostawiają plik nietknięty, a przy stanie nietkniętym krótkie
# ponowienie; 1177 (zamiennik nie dotarł, a plik wyparty JEST już pod nazwą kopii) - kopia wraca pod
# ścieżkę, a gdy to padnie, powód mówi, gdzie leży oryginał. Każdy inny błąd: stan rozpoznany z dysku.
# Zmierzone 2026-10-05 na NTFS (scratchpad): kopia dostaje `st_ino` i `mtime` pliku wypartego,
# istniejąca kopia jest nadpisywana, uchwyt bez FILE_SHARE_DELETE na pliku → 32. NIEZMIERZONE na udziale
# SMB archiwum - przed pierwszym zapisem drogą atomową na `R:` pomiar jak dla blokady (`R:\_test_blokady`).
_REPLACEFILE_FLAGS = 0x2 | 0x4          # REPLACEFILE_IGNORE_MERGE_ERRORS | REPLACEFILE_IGNORE_ACL_ERRORS
_PODMIANA_PRZEJSCIOWA = frozenset({5, 32, 33, 1175, 1176})
_PODMIANA_PONOWIENIA = (0.1, 0.3, 1.0)
_RENAME_ZAJETY = frozenset({32, 33})    # ERROR_SHARING_VIOLATION, ERROR_LOCK_VIOLATION (AR-125)
_KOPIA_SUFFIX = ".horreum-kopia"


@dataclasses.dataclass(frozen=True)
class _Odcisk:
    """Plik pod blokadą przy przygotowaniu podmiany: tożsamość (`st_ino`, rozmiar, `mtime` w ns),
    region nagłówka (`offset`, bajty) i próbki poza nim (`_probe`). Rewalidacja po wyparciu porównuje
    z nim kopię - plik, który faktycznie stał pod ścieżką w chwili podmiany."""
    ino: int
    size: int
    mtime_ns: int
    offset: int
    region: bytes
    probka: tuple


def _odcisk(fh, offset: int, length: int) -> _Odcisk:
    """Odcisk pliku z uchwytu blokady `fh` dla regionu `[offset, offset+length)`."""
    st = os.fstat(fh.fileno())
    fh.seek(offset)
    region = fh.read(length)
    if len(region) != length:
        raise ValueError(f"region {offset}:{offset + length} niekompletny ({len(region)} B)")
    return _Odcisk(st.st_ino, st.st_size, st.st_mtime_ns, offset, region,
                   _probe(fh, offset, length, st.st_size))


# Cechy pliku w powodach rozjazdu (AR-148): fragmenty z kodem, które okno nazywa w języku UI, a rdzeń
# skleja po `, ` jak dotąd (parametr-lista `features`).
_CECHA_INO = PowodPozycji("st_ino", "feat_ino")
_CECHA_ROZMIAR = PowodPozycji("rozmiar", "feat_size")
_CECHA_MTIME = PowodPozycji("mtime", "feat_mtime")
_CECHA_NAGLOWEK = PowodPozycji("nagłówek", "feat_header")
_CECHA_PROBKA = PowodPozycji("próbka danych", "feat_sample")
_CECHA_ROZMIAR_PLIKU = PowodPozycji("rozmiar pliku", "feat_file_size")
_CECHA_BAJTY_NAGLOWKA = PowodPozycji("bajty nagłówka", "feat_header_bytes")
_CECHA_HEADER_HASH = PowodPozycji("header_hash", "feat_header_hash")


def _rozjazd_odcisku(sciezka: str, odcisk: _Odcisk, *, z_mtime: bool = True) -> list[str]:
    """Czym plik `sciezka` różni się od odcisku - cechy (`PowodPozycji` z kodem `feat_*`); pusta
    lista = niczym. `z_mtime=False` dla pliku, który sami przenieśliśmy podmianą (system może
    scalić mu znaczniki czasu)."""
    with open(sciezka, "rb") as fh:
        st = os.fstat(fh.fileno())
        fh.seek(odcisk.offset)
        region = fh.read(len(odcisk.region))
        probka = _probe(fh, odcisk.offset, len(odcisk.region), st.st_size)
    return [cecha for cecha, zgodne in (
        (_CECHA_INO, not (odcisk.ino and st.st_ino) or st.st_ino == odcisk.ino),
        (_CECHA_ROZMIAR, st.st_size == odcisk.size),
        (_CECHA_MTIME, not z_mtime or st.st_mtime_ns == odcisk.mtime_ns),
        (_CECHA_NAGLOWEK, region == odcisk.region), (_CECHA_PROBKA, probka == odcisk.probka))
        if not zgodne]


def _replace_file_w(path: str, tmp: str, kopia: str) -> None:
    """`ReplaceFileW(path, tmp, kopia)` - plik `path` pod nazwę `kopia`, `tmp` pod `path`. Porażka →
    `OSError` z `winerror` i ścieżką `path` (`_blad_windows`; kopia i plik tymczasowy stoją w zdaniach
    powodów podmiany). Poza Windows → `OSError` (podmiana z backupem niedostępna)."""
    if sys.platform != "win32":
        raise OSError("podmiana z pełnym backupem wymaga Windows (ReplaceFileW)")
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.ReplaceFileW.restype = wintypes.BOOL
    k32.ReplaceFileW.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                 wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p)
    if not k32.ReplaceFileW(path, tmp, kopia, _REPLACEFILE_FLAGS, None, None):
        raise _blad_windows(ctypes.get_last_error(), path)


class _PodmianaOdbita(Exception):
    """W oknie między blokadą a podmianą ktoś zmienił plik: jego wersja wróciła pod ścieżkę, nasza
    przepadła, backup w bazie nie opisuje podmiany → 'blocked'."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class _WypartaDoPowrotu(Exception):
    """Rewalidacja po podmianie z zamiarem (AR-64) wykryła cudzą wersję pod kopią wypartą: pod
    ścieżką nasza wersja, cudza pod kopią, backup niepotwierdzony. Powrót robi automat
    rekoncyliacji orkiestracji (`_rekoncyliuj_zamiar`) - z fazami utrwalanymi przed każdą mutacją,
    czego transakcja straży (wycofywana razem z wyjątkiem) zapewnić nie może (C3)."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class _PodmianaRozdarta(Exception):
    """Stanu po podmianie nie dało się doprowadzić do zgodnego - `reason` mówi, gdzie co leży.
    `zaszla` = pod ścieżką stoi nasza wersja (wynik niesie backup), `zachowaj_tmp` = plik tymczasowy
    może być jedyną kopią danych i nie wolno go sprzątnąć."""

    def __init__(self, reason: str, *, zaszla: bool, zachowaj_tmp: bool = False):
        super().__init__(reason)
        self.reason = reason
        self.zaszla = zaszla
        self.zachowaj_tmp = zachowaj_tmp


def _nazwa_kopii(path: str) -> str:
    """Wolna nazwa kopii pliku wypartego w katalogu pliku (ten sam wolumen) - wolna RAZEM ze swoją
    kopią zwrotną (`_nazwa_zwrotna`), bo zwrotną wylicza się z niej (zamiar podmiany AR-64, ślad
    cofnięcia AR-127): podmiana systemowa nadpisuje istniejący plik kopii, więc zajęta nazwa zwrotna
    zatarłaby resztkę poprzedniej próby."""
    katalog, nazwa = os.path.split(os.path.abspath(path))
    while True:
        kopia = os.path.join(katalog, f"{nazwa}.{os.urandom(4).hex()}{_KOPIA_SUFFIX}")
        if not os.path.exists(kopia) and not os.path.exists(_nazwa_zwrotna(kopia)):
            return kopia


def _nazwa_zwrotna(kopia: str) -> str:
    """Nazwa KOPII ZWROTNEJ (AR-64) - wyliczana z nazwy kopii pliku wypartego, więc znana od chwili
    utrwalenia zamiaru podmiany: tu trafia nasza wersja, gdy wersja innego pisarza wraca pod ścieżkę.
    Śmierć procesu w oknie powrotu zostawia ją pod nazwą, którą rekoncyliacja zna (Z2). Sufiks kopii
    zostaje na końcu - skan jej nie wciąga."""
    return kopia[:-len(_KOPIA_SUFFIX)] + ".zwrot" + _KOPIA_SUFFIX


@dataclasses.dataclass(frozen=True)
class _Zamiar:
    """Zamiar podmiany drogi atomowej (0038, `repo.insert_header_backup(intent=)`): nazwy kopii
    wypartej (K), kopii zwrotnej (Z) i pliku tymczasowego (T) oraz pełny sha1 i rozmiar
    przygotowanej wersji N - policzone w strumieniu zapisu pliku tymczasowego (Z13)."""
    displaced_path: str
    return_path: str
    prepared_path: str
    prepared_sha1: str
    prepared_size: int


def _zamiar(path: str, tmp: str, sha1: str, size: int) -> _Zamiar:
    kopia = _nazwa_kopii(path)
    return _Zamiar(kopia, _nazwa_zwrotna(kopia), tmp, sha1, size)


@dataclasses.dataclass(frozen=True)
class _PrzygotowaneCofniecie:
    """Ślad cofnięcia drogą atomową (0044, `atomic_undo`) - to, co `write_full_header` za chwilę położy
    pod ścieżką, i to, co pod nią zastał, zebrane PRZED podmianą (`persist_result`, AR-182):
    wersja przygotowana (`result_*` - sha1 i rozmiar pliku tymczasowego z aktu jego zapisu, nagłówek
    formułą skanu, `byte_exact` jak w `WriteResult`), plik pod ścieżką pod blokadą (`source_*` - sha1
    z tego samego przebiegu albo z uchwytu blokady) oraz nazwy plików, które cofnięcie może zostawić na
    dysku (kopia wyparta - z niej wylicza się zwrotną, `_nazwa_zwrotna` - i plik tymczasowy, AR-127)."""
    result_sha1: str
    result_size: int
    result_hash: str
    byte_exact: bool | None
    source_sha1: str
    source_size: int
    displaced_path: str
    prepared_path: str


class _StrumienSha1:
    """Strumień zapisu liczący sha1 i rozmiar tego, co przechodzi do pliku (Z13): pełny dowód wersji
    N z aktu wytworzenia bajtów, bez drugiego pełnego odczytu pliku tymczasowego (po `R:` to drugi
    odczyt całego pliku na każdy zapis). Bez `fileno` celowo: astropy z deskryptorem pisałby dane
    obrazu z pominięciem `write` (`ndarray.tofile`), a sha1 nie objąłby danych. Zmierzone
    2026-10-12: bajty identyczne z `writeto(ścieżka)`."""
    mode = "wb"
    closed = False

    def __init__(self, fh):
        self._fh = fh
        self._sha1 = hashlib.sha1()
        self.size = 0

    def write(self, data):
        widok = memoryview(data).cast("B")
        self._sha1.update(widok)
        self.size += len(widok)
        return self._fh.write(widok)

    def flush(self):
        self._fh.flush()

    def tell(self):
        return self.size

    def seek(self, *_a):
        raise OSError("strumień liczący sha1 nie przewija")

    def seekable(self):
        return False

    def hexdigest(self) -> str:
        return self._sha1.hexdigest()


def _zapisz_tymczasowy_fits(hdul, tmp: str) -> _StrumienSha1:
    """Plik tymczasowy drogi atomowej FITS (nowy plik z `mkstemp`, nigdy plik usera) zapisany przez
    strumień liczący sha1 i rozmiar (Z13) - pełny dowód wersji N bez drugiego odczytu."""
    with open(tmp, "wb") as dst:
        strumien = _StrumienSha1(dst)
        hdul.writeto(strumien)
    return strumien


def _sha1_pliku(path: str) -> tuple[str, int] | None:
    """Pełny sha1 i rozmiar pliku albo `None`, gdy pliku nie ma - jedyne rozpoznanie wersji
    w rekoncyliacji zamiaru podmiany (A/N/B, AR-64): nagłówek nie odróżnia wersji o tym samym
    nagłówku i innych danych (Z1, Z12)."""
    try:
        with open(path, "rb") as fh:
            h, n = hashlib.sha1(), 0
            while True:
                b = fh.read(_SHA1_BUF)
                if not b:
                    return h.hexdigest(), n
                h.update(b)
                n += len(b)
    except FileNotFoundError:
        return None


def _replace_z_ponowieniem(path: str, tmp: str, kopia: str) -> OSError | None:
    """`_replace_file_w` z krótkim ponowieniem błędu przejściowego (`_PODMIANA_PRZEJSCIOWA`:
    antywirus, indeksowanie) - wyłącznie przy stanie nietkniętym na dysku (plik i zamiennik pod
    swoimi nazwami, kopii brak). Zwraca `None` albo ostatni błąd."""
    for pauza in (*_PODMIANA_PONOWIENIA, None):
        try:
            _replace_file_w(path, tmp, kopia)
            return None
        except OSError as exc:
            nietkniety = os.path.exists(path) and os.path.exists(tmp) and not os.path.exists(kopia)
            if (pauza is None or not nietkniety
                    or getattr(exc, "winerror", None) not in _PODMIANA_PRZEJSCIOWA):
                return exc
            time.sleep(pauza)
    return None


def _kopia_na_miejsce(kopia: str, path: str) -> None:
    """Kopia pod pustą ścieżkę (`os.rename`, stan 1177 - bez nadpisania czegokolwiek) z tym samym
    krótkim ponowieniem błędu przejściowego co podmiana, dopóki kopia stoi na dysku. Na udziale SMB
    (`R:`, sonda 2026-10-05) plik świeżo dotknięty przez podmianę bywa przez chwilę zajęty.
    Ostatni błąd → wyjątek dalej."""
    for pauza in (*_PODMIANA_PONOWIENIA, None):
        try:
            os.rename(kopia, path)
            return
        except OSError as exc:
            if (pauza is None or not os.path.exists(kopia)
                    or getattr(exc, "winerror", None) not in _PODMIANA_PRZEJSCIOWA):
                raise
            time.sleep(pauza)


def _czy_zaszla(path: str, tmp: str, kopia: str, blad: OSError | None) -> bool:
    """Rozpoznanie z dysku po wywołaniu podmiany: `True` = pod ścieżką stoi zamiennik, a plik wyparty
    pod nazwą kopii (także gdy system zgłosił błąd, a podmiana zaszła - zerwany udział); `False` =
    plik pod ścieżką nietknięty. Stan 1177 (wyparty pod kopią, pod ścieżką nic) - kopia wraca pod
    ścieżkę; każdy stan, którego nie da się doprowadzić do jednego z dwóch → `_PodmianaRozdarta`."""
    jest_sciezka, jest_kopia = os.path.exists(path), os.path.exists(kopia)
    if blad is None:
        if jest_sciezka and jest_kopia:
            return True
        raise _PodmianaRozdarta(PowodPozycji(
            f"system zgłosił podmianę, ale kopii pliku wypartego ({kopia}) brak - nie da się "
            f"sprawdzić, czy ktoś zmienił plik w oknie podmiany", "replace_copy_missing",
            copy=kopia), zaszla=jest_sciezka, zachowaj_tmp=not jest_sciezka)
    if jest_sciezka:
        return jest_kopia
    blad_podmiany = _blad_systemu(blad, z_typem=False)
    if jest_kopia:
        try:
            _kopia_na_miejsce(kopia, path)
        except OSError as exc:
            blad_powrotu = _blad_systemu(exc, z_typem=False)
            raise _PodmianaRozdarta(PowodPozycji(
                f"podmiana przerwana ({blad_podmiany}): oryginał leży pod {kopia}, a pod {path} "
                f"pliku nie ma; powrót kopii też padł ({blad_powrotu}) - przenieś {kopia} na "
                f"{path} ręcznie", "replace_cut_copy_back_failed", detail=blad_podmiany,
                copy=kopia, path=path, error=blad_powrotu), zaszla=False) from exc
        return False
    raise _PodmianaRozdarta(PowodPozycji(
        f"podmiana przerwana ({blad_podmiany}): ani {path}, ani kopia {kopia} nie istnieją - dane "
        f"pliku są w pliku tymczasowym {tmp}, zostaje na dysku", "replace_cut_both_missing",
        detail=blad_podmiany, path=path, copy=kopia, tmp=tmp), zaszla=False, zachowaj_tmp=True)


def _oddaj_wyparty(path: str, kopia: str, rozjazd: list[str], nasza: _Odcisk) -> None:
    """Rewalidacja po wyparciu nie przeszła: wyparta wersja B (cudza zmiana z okna podmiany) wraca
    pod ścieżkę, nasza N przepada → `_PodmianaOdbita`.

    POWRÓT TEŻ ZACHOWUJE PLIK WYPIERANY (bramka astra, A1): `ReplaceFileW(path, kopia, zwrotna)` -
    to, co stoi pod ścieżką, trafia pod drugą kopię i musi być NASZĄ wersją N (`nasza` - odcisk
    pliku tymczasowego sprzed podmiany, bez `mtime`, który podmiana może scalić). Trzeci pisarz
    w oknie powrotu (wydłużonym ponowieniami) dałby pod drugą kopią swoją wersję C - wtedy
    wszystkie wersje zostają na dysku, a powód podaje każdą ścieżkę. Dawniej `os.replace(kopia, path)`
    kasował C bez śladu, a wynik mówił, że cudza wersja wróciła.
    Powrót, który nie zajdzie (po ponowieniach błędu przejściowego) → `_PodmianaRozdarta`: N pod
    ścieżką, B pod kopią, obie zostają.

    Wyłącznie droga BEZ zamiaru podmiany (cofnięcie atomowe): zapis z zamiarem oddaje cudzą wersję
    automatem rekoncyliacji (`_WypartaDoPowrotu` → `_rekoncyliuj_zamiar`, AR-64 C3). Nazwa drugiej
    kopii wynika z nazwy kopii wypartej (`_nazwa_zwrotna`, wolna razem z nią - `_nazwa_kopii`), więc
    ślad cofnięcia, który utrwala kopię wypartą, zna też ją (AR-127)."""
    zmiana = _zmiana_w_oknie(rozjazd)
    zwrotna = _nazwa_zwrotna(kopia)
    blad = _replace_z_ponowieniem(path, kopia, zwrotna)
    try:
        zaszedl = _czy_zaszla(path, kopia, zwrotna, blad)
    except _PodmianaRozdarta as exc:
        raise _PodmianaRozdarta(PowodPozycji(
            f"{zmiana}; powrót wersji innego pisarza ({kopia}) przerwany: {exc.reason}",
            "return_cut", change=zmiana, copy=kopia, inner=exc.reason),
            zaszla=False, zachowaj_tmp=True) from exc
    if not zaszedl:
        blad_powrotu = _blad_systemu(blad, z_typem=False)
        raise _PodmianaRozdarta(PowodPozycji(
            f"{zmiana} - pod {path} stoi wersja zbudowana ze stanu SPRZED tej zmiany, a wersja "
            f"innego pisarza leży pod {kopia}; jej powrót padł ({blad_powrotu}) - przenieś {kopia} "
            f"na {path} ręcznie", "return_failed_manual", change=zmiana, path=path, copy=kopia,
            detail=blad_powrotu), zaszla=True)
    try:
        obca = _rozjazd_odcisku(zwrotna, nasza, z_mtime=False)
    except OSError as exc:
        blad_odczytu = _blad_systemu(exc, z_typem=False)
        obca = [PowodPozycji(f"nieczytelny ({blad_odczytu})", "feat_unreadable",
                             detail=blad_odczytu)]
    if obca:
        raise _PodmianaRozdarta(PowodPozycji(
            f"{zmiana}, a w oknie powrotu kolejny pisarz zmienił plik ({', '.join(obca)}): pod "
            f"{path} wersja innego pisarza z okna podmiany, pod {zwrotna} wersja wyparta w oknie "
            f"powrotu - obie zostają, rozstrzygnij ręcznie; zmiana NIE zapisana", "third_writer",
            change=zmiana, features=obca, path=path, copy=zwrotna), zaszla=False)
    uwaga = _usun_kopie(zwrotna)
    raise _PodmianaOdbita(_dopisz(PowodPozycji(
        f"{zmiana} - wersja innego pisarza wróciła na miejsce, zmiana NIE zapisana; ponów po "
        f"odświeżeniu stagingu", "other_writer_returned", change=zmiana), uwaga))


def _zmiana_w_oknie(rozjazd) -> PowodPozycji:
    """Fragment „plik zmienił się między odczytem a podmianą (cechy)” - cechy z kodem
    (`_rozjazd_odcisku`), okno nazywa je w języku UI (AR-148)."""
    return PowodPozycji(f"plik zmienił się między odczytem a podmianą ({', '.join(rozjazd)})",
                        "changed_in_window", features=rozjazd)


def _podmien(tmp: str, path: str, replace_guard, odcisk: _Odcisk, po_podmianie=None, *,
             zamiar: _Zamiar | None = None, kopia: str | None = None) -> str | None:
    """PODMIANA SYSTEMOWA (sekcja wyżej): `ReplaceFileW` z kopią pliku wypartego, rozpoznanie stanu
    z dysku, rewalidacja kopii wobec `odcisk` i sprzątnięcie kopii. Zwraca uwagę dla wyniku (kopia,
    której nie dało się skasować) albo `None`; błąd podmiany przy pliku nietkniętym albo podmienionym
    mimo błędu → ten błąd (`OSError`), wyparcie cudzej zmiany → `_PodmianaOdbita`, stan bez zgody
    z dyskiem → `_PodmianaRozdarta`.

    Pod STRAŻĄ PODMIANY, gdy wołający ją podał (`replace_guard()`, orkiestracja podaje
    `repo.guard_file_replace`): straż sprawdza stan bazy i trzyma jej blokadę zapisu przez podmianę
    i rewalidację; odmowa (`repo.InplaceConflict`) wychodzi PRZED podmianą, plik nietknięty.
    `po_podmianie()` (potwierdzenie backupu w bazie, AR-40) idzie w transakcji straży - wyłącznie
    po podmianie zgłoszonej przez system i zgodnej rewalidacji; jego porażka zostawia backup
    niepotwierdzony (rekoncyliacja z dyskiem go rozstrzygnie), więc jest połykana. Błąd przy
    ZAMKNIĘCIU straży już po podmianie nie cofa podmiany - też połykany (o wyniku mówi weryfikacja
    po podmianie).

    ZAMIAR PODMIANY (AR-64): `zamiar` niesie nazwy kopii wypartej i zwrotnej (utrwalone z backupem
    przed tą chwilą) i pełny sha1 naszej wersji. Kopia wyparta znika wyłącznie po POTWIERDZONYM
    backupie (`po_podmianie` i zamknięcie straży bez błędu): gdy potwierdzenie przepadło, backup
    zostaje niepotwierdzony, a kopia jest dowodem dla rekoncyliacji (Z12) - ta ją sprzątnie po
    rozpoznaniu pełnym sha1. Cudza wersja wykryta rewalidacją przy zamiarze NIE wraca tutaj:
    `_WypartaDoPowrotu` wycofuje straż, a powrót robi automat rekoncyliacji orkiestracji (C3).

    `kopia` (bez zamiaru) = nazwa kopii pliku wypartego wybrana przez wołającego (`_nazwa_kopii`) -
    cofnięcie atomowe utrwala ją w śladzie przed tą chwilą (AR-127); bez niej nazwa wybierana tutaj."""
    if zamiar is not None:
        kopia = zamiar.displaced_path
    elif kopia is None:
        kopia = _nazwa_kopii(path)
    nasza = None
    if zamiar is None:
        with open(tmp, "rb") as fh:      # odcisk NASZEJ wersji - powrót wypartego ją rozpozna (A1)
            nasza = _odcisk(fh, 0, min(_PROBE_BYTES, os.fstat(fh.fileno()).st_size))
    potwierdzone = po_podmianie is None
    straz = replace_guard() if replace_guard is not None else contextlib.nullcontext()
    straz.__enter__()
    try:
        blad = _replace_z_ponowieniem(path, tmp, kopia)
        zaszla = _czy_zaszla(path, tmp, kopia, blad)
        if zaszla:
            try:
                rozjazd = _rozjazd_odcisku(kopia, odcisk)
            except OSError as exc:
                blad_odczytu = _blad_systemu(exc, z_typem=False)
                raise _PodmianaRozdarta(PowodPozycji(
                    f"plik podmieniony, ale kopii pliku wypartego nie da się przeczytać "
                    f"({blad_odczytu}) - zostaje pod {kopia}", "displaced_unreadable",
                    detail=blad_odczytu, copy=kopia), zaszla=True) from exc
            if rozjazd and zamiar is not None:
                # C3: powrót cudzej wersji idzie WYŁĄCZNIE wspólnym automatem rekoncyliacji
                # (trwałe fazy w osobnych transakcjach) - po wycofaniu straży, nie w niej.
                raise _WypartaDoPowrotu(_zmiana_w_oknie(rozjazd))
            if rozjazd:
                _oddaj_wyparty(path, kopia, rozjazd, nasza)
            if blad is None and po_podmianie is not None:
                try:
                    po_podmianie()
                    potwierdzone = True
                except Exception:  # noqa: BLE001 - backup zostaje niepotwierdzony (docstring)
                    pass
    except BaseException:
        if not straz.__exit__(*sys.exc_info()):
            raise
        return None
    try:
        straz.__exit__(None, None, None)
    except Exception:  # noqa: BLE001 - podmiana już zaszła (docstring)
        potwierdzone = False
    if zaszla and not potwierdzone and zamiar is not None:
        uwaga = PowodPozycji(
            f"potwierdzenie podmiany w bazie przepadło - kopia pliku sprzed zapisu zostaje pod "
            f"{kopia} do rekoncyliacji (następny zapis albo cofnięcie tej lokacji)",
            "confirm_lost_copy_kept", copy=kopia)
    elif zaszla and not potwierdzone:
        # C6: bez zamiaru (cofnięcie) nie ma backupu do rekoncyliacji - kopii nikt nie sprzątnie.
        uwaga = PowodPozycji(
            f"zamknięcie transakcji podmiany padło - kopia pliku sprzed tej operacji została pod "
            f"{kopia} i nic jej nie sprzątnie; zgodna z plikiem sprzed operacji - po sprawdzeniu "
            f"można ją skasować ręcznie", "close_failed_copy_left", copy=kopia)
    else:
        uwaga = _usun_kopie(kopia) if zaszla else None
    if blad is not None:
        raise blad
    return uwaga


def _usun_kopie(kopia: str) -> str | None:
    """Sprzątnij kopię pliku wypartego (zgodną z odciskiem - nic na niej nie ginie). Porażka po
    ponowieniach → uwaga dla wyniku z nazwą kopii, nie błąd zapisu."""
    for pauza in (*_PODMIANA_PONOWIENIA, None):
        try:
            os.remove(kopia)
            return None
        except FileNotFoundError:
            return None
        except OSError as exc:
            if pauza is None:
                blad = _blad_systemu(exc)
                return PowodPozycji(f"kopia pliku sprzed podmiany została pod {kopia} ({blad}) - "
                                    f"zgodna z plikiem sprzed zapisu, można ją skasować",
                                    "copy_not_removed", copy=kopia, detail=blad)
            time.sleep(pauza)
    return None


def _zloz_plik_tymczasowy(path: str, fh, czesci, *, oryginal_region: bytes | None = None):
    """Plik tymczasowy w katalogu `path` (ten sam wolumen) złożony z `czesci`: `bytes` albo zakres
    `(od, do)` z uchwytu `fh` (`do=None` = do końca pliku). Zwraca `(tmp, sha1 tmp, sha1 oryginału)`.

    `oryginal_region` - bajty, które w pliku oryginalnym stoją w miejscu JEDYNEJ części `bytes`:
    sha1 oryginału liczy się wtedy z tego samego przebiegu po ogonie, bez drugiego pełnego odczytu
    (kotwica bajtowego cofnięcia, `RegionBackup.file_sha1`, AR-19). Porażka → plik tymczasowy
    sprzątnięty, wyjątek dalej."""
    if oryginal_region is not None and sum(isinstance(c, bytes) for c in czesci) != 1:
        raise ValueError("oryginal_region wymaga dokładnie jednej części bajtowej")
    fd, tmp = tempfile.mkstemp(suffix=".tmp", dir=os.path.dirname(os.path.abspath(path)))
    os.close(fd)
    h_tmp = hashlib.sha1()
    h_org = hashlib.sha1() if oryginal_region is not None else None
    try:
        with open(tmp, "wb") as dst:
            for czesc in czesci:
                if isinstance(czesc, bytes):
                    dst.write(czesc)
                    h_tmp.update(czesc)
                    if h_org is not None:
                        h_org.update(oryginal_region)
                    continue
                od, do = czesc
                fh.seek(od)
                zostalo = None if do is None else do - od
                while zostalo is None or zostalo > 0:
                    b = fh.read(_SHA1_BUF if zostalo is None else min(_SHA1_BUF, zostalo))
                    if not b:
                        break
                    dst.write(b)
                    h_tmp.update(b)
                    if h_org is not None:
                        h_org.update(b)
                    if zostalo is not None:
                        zostalo -= len(b)
                if zostalo:
                    raise ValueError(f"zakres {od}:{do} pliku niekompletny (brak {zostalo} B)")
    except BaseException:
        os.remove(tmp)
        raise
    return tmp, h_tmp.hexdigest(), None if h_org is None else h_org.hexdigest()


def _coerce(value, value_type: str):
    """Wartość wpisu stagingu (tekst) w typie karty. Tekst, który nie jest liczbą typu karty, to ODMOWA
    łaty z kodem bliźniaczym podglądu (`macro_type_mismatch`, AR-256) - plik nietknięty; dawniej goły
    `ValueError` z `int()` dawał 'failed' prozą. W produkcie zatrzymuje to wcześniej podgląd makra."""
    if value_type in ("int", "float"):
        try:
            return int(value) if value_type == "int" else float(value)
        except (TypeError, ValueError) as exc:
            tekst = str(value)
            raise OdmowaZPowodem(PowodPozycji(
                f"wartość '{tekst}' nie pasuje do typu '{value_type}'", "macro_type_mismatch",
                value=tekst, value_type=value_type)) from exc
    if value_type == "bool":
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("t", "true", "1", "yes")
    return str(value)


def _count_keyword(hdr, keyword: str) -> int:
    return sum(1 for c in hdr.cards if c.keyword == keyword)


# ODMOWY ŁATY Z KODEM PODGLĄDU (AR-232, AR-256): pisarz odmawia tych samych łat co podgląd makra
# (`macro._evaluate_change`) i tymi samymi zdaniami - wołający bez kotwicy stagingu (API) dostaje
# 'blocked' z kodem, plik nietknięty. Obie drogi FITS (atomowa i plan w miejscu - przebieg próbny
# `_apply_op`) i XISF mówią „karta już jest” jednym kodem.
def _karta_juz_jest(keyword: str) -> PowodPozycji:
    """`add` karty, która już jest - JEDNO zdanie i kod dla FITS i XISF (bliźniak podglądu makra)."""
    return PowodPozycji(f"karta '{keyword}' już istnieje (użyj set)", "macro_add_exists",
                        keyword=keyword)


def _wymagany_idx(keyword: str) -> PowodPozycji:
    """`set` bez `idx` na karcie powtórzonej - bliźniak podglądu makra; dawniej pisarz zapisywał po
    cichu PIERWSZE wystąpienie (FITS i XISF)."""
    return PowodPozycji(f"keyword '{keyword}' ma wiele wystąpień -- wymagany jawny idx",
                        "macro_idx_required", keyword=keyword)


def _brak_wystapienia(keyword: str, idx: int, ile: int) -> PowodPozycji:
    """`set` wystąpienia `idx`, którego w nagłówku nie ma (`ile` wystąpień) - ta sama odmowa co
    bramka zakresu podglądu makra."""
    return PowodPozycji(f"karta '{keyword}' nie ma wystąpienia [{idx}] - w nagłówku jest ich {ile}",
                        "card_idx_missing", keyword=keyword, idx=idx, n=ile)


def _set_nth(hdr, keyword: str, n: int, value, comment: str | None) -> None:
    seen = -1
    for card in hdr.cards:
        if card.keyword == keyword:
            seen += 1
            if seen == n:
                card.value = value
                if comment is not None:
                    card.comment = comment
                return
    raise OdmowaZPowodem(_brak_wystapienia(keyword, n, seen + 1))


def _apply_op(hdr, op: WriteOp) -> None:
    value = _coerce(op.value, op.value_type)
    if op.op == "add":
        # Jawne dodanie BRAKUJACEGO keyworda (astropy dopisuje na koniec). Gdy keyword juz jest, `add`
        # nie nadpisuje cicho (to robi `set`) - odmowa z kodem bliźniaczym podglądu makra
        # (`macro_add_exists`, AR-232), plik nietknięty. W produkcie ten stan zatrzymuje wcześniej
        # kotwica `header_hash` stagingu (nowa karta zmienia nagłówek); tu dochodzi wołający bez kotwicy.
        if _count_keyword(hdr, op.keyword) > 0:
            raise OdmowaZPowodem(_karta_juz_jest(op.keyword))
        hdr[op.keyword] = (value, op.comment) if op.comment is not None else value
        return
    if op.op == "set":
        if op.idx is None and _count_keyword(hdr, op.keyword) > 1:
            raise OdmowaZPowodem(_wymagany_idx(op.keyword))
        if (op.idx in (None, 0)) and _count_keyword(hdr, op.keyword) <= 1:
            hdr[op.keyword] = (value, op.comment) if op.comment is not None else value
        else:
            _set_nth(hdr, op.keyword, op.idx or 0, value, op.comment)
        return
    raise ValueError(f"nieznana operacja: {op.op!r}")


def _nth_card(hdr, keyword: str, n: int):
    """`n`-te wystąpienie karty `keyword` (nazwa jak u astropy: wielkie litery) albo `None`."""
    return next((c for i, c in enumerate(c for c in hdr.cards if c.keyword == keyword) if i == n),
                None)


def _fits_comments_before(hdr, ops: list[WriteOp]) -> dict:
    """Zastane komentarze kart, które `set` BEZ komentarza przełoży:
    `(keyword, n) → (obraz, komentarz)`. Liczone PRZED `_apply_op` - astropy przy zmianie wartości układa kartę od nowa, a tylko obraz
    sprzed zmiany mówi, jaki komentarz karta niosła. `set` z komentarzem pomijamy: ten komentarz
    wnosi łata i jego długość sprawdza `card_violation`."""
    przed = {}
    for op in ops:
        if op.op != "set" or op.comment is not None:
            continue
        kw, n = op.keyword.strip().upper(), op.idx or 0
        card = _nth_card(hdr, kw, n)
        if card is not None and card.comment:
            przed[(kw, n)] = (card.image, card.comment)
    return przed


def _fits_comment_loss(hdr, przed: dict) -> str | None:
    """AR-7: powód odmowy, gdy przełożona karta straciła zastany komentarz, albo `None`.

    astropy układa zmienioną kartę w stałym formacie (pole wartości od kolumny 11 do co najmniej
    30) i komentarz, który się nie zmieści, UCINA po cichu - dawniej wynik 'applied' z komentarzem
    62 → 47 znaków. To ta sama kontrola, którą droga w miejscu robi round-tripem obrazu karty
    (`_obraz_karty`): obraz po zmianie, przeczytany z powrotem, ma nieść ten sam komentarz.

    Zapis TOŻSAMOŚCIOWY (obraz karty bez zmian - astropy nie przekłada karty, której wartość się
    nie zmieniła) jest poza kontrolą: nie zmienia ani bajtu karty, więc niczego nie ucina, a jego
    odmowa zablokowałaby przepisanie wartości aktualnej na kartach z zastanym długim komentarzem.

    Odmowa zamiast zachowania komentarza: zachowanie wymagałoby własnego układu karty (wolny format,
    komentarz bliżej wartości), czyli drugiego właściciela układu obok astropy - a układ astropy
    przewiduje też podgląd drogi zapisu (`inplace_route`)."""
    for (kw, n), (obraz, komentarz) in przed.items():
        card = _nth_card(hdr, kw, n)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            nowy = card.image
            if nowy == obraz:
                continue
            zostal = fits.Card.fromstring(nowy).comment or ""
        if zostal != komentarz:
            return _powod_ucietego_komentarza(kw, len(komentarz), len(zostal))
    return None


def _powod_ucietego_komentarza(kw: str, przed: int, po: int) -> str:
    """Jedno brzmienie odmowy AR-7 - dla pisarza (`_fits_comment_loss`) i podglądu planu
    (`comment_loss_route`), żeby plan mówił DOKŁADNIE to, co potem powiedziałby zapis. Z długości
    komentarza przed i po układzie karty - tych samych faktów, które `comment_loss_lengths` daje
    powierzchniom mówiącym własnym językiem (AR-138). Z kodem (AR-148) - okna zapisu mówią to samo
    zdanie w języku UI."""
    return PowodPozycji(f"zmiana wartości karty {kw} ucięłaby zastany komentarz z {przed} do "
                        f"{po} znaków (karta FITS po zmianie ma pole wartości stałego formatu) "
                        f"- plik nietknięty; zapisz zmianę razem z komentarzem skróconym do "
                        f"{po} znaków albo wybierz krótszą wartość", "comment_cut", keyword=kw,
                        before=przed, after=po)


def _is_xisf(path) -> bool:
    """Dyspozycja pisarza po rozszerzeniu — TA SAMA reguła co czytnika (`scan.XISF_SUFFIXES`,
    case-insensitive), żeby zapis i odczyt nigdy nie rozjechały się co do formatu."""
    return os.path.splitext(os.fspath(path))[1].lower() in scan.XISF_SUFFIXES


def _is_raw(path) -> bool:
    """Czy plik to DSLR/RAW (.dng/.arw/.cr2) — SPOT z `exif.RAW_SUFFIXES` (#2). RAW jest READ-ONLY
    dla Horreum: pisarz ODMAWIA przed dyspozycją FITS/XISF, inaczej `.dng` wpadłby w `fits.open`
    (crash, nie czyste `blocked`; znal.4)."""
    return exif.is_raw(path)


def _post_hash(path: str) -> str:
    """header_hash z ZAPISANEGO pliku — LICZONY TĄ SAMĄ formułą co skan (FITS: `read_fits_meta` →
    `scan._header_hash`; XISF: `read_xisf_meta_full` → sha1 bajtów XML, D-X-3), więc przyszły
    re-skan i undo-guard dostają identyczny hash (brief T3)."""
    if _is_xisf(path):
        return scan.read_xisf_meta_full(path).header_hash
    return scan.read_fits_meta(path).header_hash


def write_changes(path, ops: list[WriteOp], expected_hash: str | None, *,
                  persist_backup: Callable[[str, str, _Zamiar], None] | None = None,
                  replace_guard=None, confirm_backup: Callable[[], None] | None = None) -> WriteResult:
    """Atomowo zapisz zmiany w nagłówku wybranego HDU. Kontrola `header_hash`: nagłówek na dysku ≠
    `expected_hash` → 'blocked', NIE pisze. Treść łamiąca reguły karty FITS 4.0 (`card_violation`)
    → 'blocked' z powodem, NIE pisze - zamiast angielskiego wyjątku astropy albo cichego CONTINUE,
    ucięcia komentarza czy karty HIERARCH. FITS z kartą `CHECKSUM`/`DATASUM` → 'blocked' tą samą
    odmową co zapis w miejscu (`_odmowa_sumy`, AR-166): pełne przepisanie zostawiłoby sumę
    niezgodną z plikiem. Zmiana wartości, po której astropy uciąłby ZASTANY
    komentarz karty, też → 'blocked' (`_fits_comment_loss`, AR-7). Plik tymczasowy jest czytany
    PRZED podmianą (plik nieczytelny nie zastąpi oryginału), a jego hash jest kotwicą weryfikacji
    po podmianie (`_after_replace`). Zwraca `post_hash` z zapisanego pliku + `backup_text` - także
    przy 'failed' PO podmianie. Port dawcy `fits_io.write_changes`.
    `.xisf` → `write_xisf_changes` (inny format, TEN SAM kontrakt `WriteResult`).
    `.dng/.arw/.cr2` → ODMOWA (#2): RAW jest read-only (rename dozwolony osobno).

    BACKUP PRZED PODMIANĄ (Z3, 2026-09-26): `backup_text` = `RegionBackup` (surowy region nagłówka
    sprzed zmian + metadane), a `persist_backup(backup_text, post_hash, zamiar)` - gdy podany -
    utrwala go w bazie PRZED `os.replace`, razem z zamiarem podmiany (`_Zamiar`, AR-64: nazwy kopii
    i pełny sha1 pliku tymczasowego policzony w strumieniu zapisu, Z13). Porażka backupu → 'failed',
    oryginał nietknięty, plik tymczasowy sprzątnięty. Dawniej backup powstawał PO podmianie, więc
    jego porażka zostawiała plik zmieniony bez drogi powrotu.

    STRAŻ PODMIANY (`replace_guard`, astra 2026-09-27): `os.replace` idzie pod menedżerem kontekstu
    wołającego (`_podmien`) - orkiestracja podaje `repo.guard_file_replace`, która w transakcji
    zapisu bazy sprawdza, że od bramki izolacji nikt nie zaczął na tej lokacji zapisu w miejscu.
    Odmowa (`repo.InplaceConflict`) → 'blocked' z powodem, plik nietknięty, plik tymczasowy
    sprzątnięty; backup został utrwalony wcześniej i zostaje (append-only, nigdy nie wskaże bajtów,
    których nie było - undo takiego backupu rozpozna nagłówek inny niż `post_hash` i odmówi).
    Wynik bez `backup_text` mówi orkiestracji „pliku nie ruszono": `commit` nie oddaje wtedy
    `commit_id`, więc przebieg bez żadnej podmiany nie dostaje przycisku cofnięcia.

    POD BLOKADĄ I Z PODMIANĄ SYSTEMOWĄ (AR-18, sekcja „PODMIANA SYSTEMOWA"): odczyt, plik
    tymczasowy, region backupu i sha1 całego pliku (`RegionBackup.file_sha1` - kotwica bajtowego
    cofnięcia, AR-19; jeden pełny odczyt więcej) powstają pod `_exclusive`; podmiana `ReplaceFileW`
    z kopią pliku wypartego i rewalidacją kopii. Cudza zmiana w oknie podmiany → 'blocked', jej
    wersja wraca na miejsce. `confirm_backup()` = potwierdzenie backupu w bazie w transakcji straży
    (AR-40) - wyłącznie po podmianie zgłoszonej przez system i zgodnej rewalidacji."""
    if _is_raw(path):
        return WriteResult("blocked", _RAW_READ_ONLY, None)
    if _is_xisf(path):
        return write_xisf_changes(path, ops, expected_hash, persist_backup=persist_backup,
                                  replace_guard=replace_guard, confirm_backup=confirm_backup)
    path = os.fspath(path)
    tmp: str | None = None
    zachowaj_tmp = False
    written_hash = backup_text = None
    try:
        with _exclusive(path) as fh:
            with fits.open(path, mode="readonly", memmap=False) as hdul:
                index, hdu = scan._select_hdu(hdul)
                hdr = hdu.header
                current = scan._header_hash(hdr)
                if expected_hash is not None and current != expected_hash:
                    return WriteResult("blocked", _HEADER_HASH_MISMATCH, None)
                # Nowa karta = `add` ALBO `set` na karcie nieobecnej - tę `_apply_op` dopisuje po
                # cichu (semantyka astropy), więc jej nazwa też jest treścią wniesioną przez łatę.
                powod = _ops_violation(
                    ops, lambda op: op.op == "add" or _count_keyword(hdr, op.keyword) == 0)
                if powod is not None:
                    return WriteResult("blocked", powod, None)
                # AR-166: suma kontrolna - ta sama odmowa i to samo miejsce kolejki co w miejscu.
                powod = _odmowa_sumy(hdr)
                if powod is not None:
                    return WriteResult("blocked", powod, None)
                info = hdul.fileinfo(index)
                start, data_start = info["hdrLoc"], info["datLoc"]
                komentarze = _fits_comments_before(hdr, ops)
                # Odmowa łaty (`add` na karcie, która już jest, AR-232) - przed plikiem tymczasowym,
                # jak bramki wyżej. Wąsko wokół `_apply_op`: odmowa z kodem dalej w `try` (np. z klingi
                # po podmianie) nie może udawać pliku nietkniętego.
                try:
                    for op in ops:
                        _apply_op(hdr, op)
                except OdmowaZPowodem as exc:
                    return WriteResult("blocked", exc.powod, None)
                powod = _fits_comment_loss(hdr, komentarze)      # AR-7: przed plikiem tymczasowym
                if powod is not None:
                    return WriteResult("blocked", powod, None)
                fd, tmp = tempfile.mkstemp(suffix=".tmp",
                                           dir=os.path.dirname(os.path.abspath(path)))
                os.close(fd)
                strumien = _zapisz_tymczasowy_fits(hdul, tmp)
            # Odczyt pliku tymczasowego TĄ SAMĄ formułą co skan, zanim zastąpi oryginał: nieczytelny
            # → 'failed' i oryginał nietknięty; czytelny → hash tego, co za chwilę będzie na dysku
            # (kotwica `_after_replace`).
            written_hash = scan.read_fits_meta(tmp).header_hash
            odcisk = _odcisk(fh, start, data_start - start)
            backup_text = RegionBackup("fits", start, odcisk.region, odcisk.size, odcisk.ino,
                                       current, _sha1_uchwytu(fh)).encode()
        zamiar = _zamiar(path, tmp, strumien.hexdigest(), strumien.size)
        if persist_backup is not None:
            try:
                persist_backup(backup_text, written_hash, zamiar)
            except Exception as exc:  # noqa: BLE001 - bez backupu nie podmieniamy
                return WriteResult("failed", _backup_nie_powstal(exc), None)
        uwaga = _podmien(tmp, path, replace_guard, odcisk, confirm_backup,
                         zamiar=zamiar if persist_backup is not None else None)
        tmp = None
    except repo.InplaceConflict as exc:                    # straż odbiła podmianę - plik nietknięty
        return WriteResult("blocked", _powod_konfliktu(exc.op), None)
    except _PodmianaOdbita as exc:                         # cudza zmiana wróciła na miejsce
        return WriteResult("blocked", exc.reason, None)
    except _WypartaDoPowrotu as exc:                       # powrót zrobi automat orkiestracji
        return WriteResult("failed", exc.reason, None, code=CODE_POWROT_WYPARTEJ)
    except _PodmianaRozdarta as exc:
        zachowaj_tmp = exc.zachowaj_tmp
        return WriteResult("failed", exc.reason, written_hash if exc.zaszla else None,
                           backup_text if exc.zaszla else None)
    except Exception as exc:  # noqa: BLE001 - raport zamiast wyjątku w warstwie zapisu
        return WriteResult("failed", _blad_systemu(exc), None)
    finally:
        _sprzatnij_tmp(tmp, zachowaj_tmp)
    return _after_replace(path, written_hash, backup_text, uwaga)   # T3: hash z ZAPISANEGO pliku


def _backup_nie_powstal(exc) -> PowodPozycji:
    """Powód drogi atomowej (FITS i XISF), gdy backup do cofnięcia nie wszedł do bazy przed
    podmianą - pliku nie ruszono."""
    blad = _blad_systemu(exc)
    return PowodPozycji(f"backup do cofnięcia NIE powstał, więc podmiany nie było - plik "
                        f"nietknięty: {blad}", "backup_not_saved", detail=blad)


def _slad_nie_powstal(exc) -> PowodPozycji:
    """Powód cofnięcia atomowego, gdy ślad wyniku (`atomic_undo`, AR-182) nie wszedł do bazy przed
    podmianą - pliku nie ruszono."""
    blad = _blad_systemu(exc)
    return PowodPozycji(f"ślad cofnięcia NIE powstał w bazie, więc podmiany nie było - plik "
                        f"nietknięty: {blad}", "undo_record_not_saved", detail=blad)


def _sprzatnij_tmp(tmp: str | None, zachowaj: bool) -> None:
    """Plik tymczasowy, którego podmiana nie zużyła - precz, chyba że `zachowaj`
    (`_PodmianaRozdarta.zachowaj_tmp`: może być jedyną kopią danych)."""
    if tmp is not None and not zachowaj and os.path.exists(tmp):
        try:
            os.remove(tmp)
        except OSError:
            pass


def write_full_header(path, header_text: str, expected_hash: str | None, *,
                      replace_guard=None,
                      persist_result: Callable[[_PrzygotowaneCofniecie], None] | None = None,
                      expect_file_sha1: str | None = None) -> WriteResult:
    """Atomowo przywróć nagłówek z backupu (ścieżka undo): plik tymczasowy + `os.replace`. Kontrola
    `header_hash` jak w `write_changes` (dysk ≠ `expected_hash` → 'blocked'). `header_text` = backup
    dowolnej generacji: koperta `RegionBackup` (od 2026-09-26) albo tekst sprzed niej
    (`hdr.tostring()` dla FITS, XML dla XISF). Dane nietknięte (`sha1_data` zostaje).
    `.dng/.arw/.cr2` → ODMOWA (#2).

    Cofnięcie W MIEJSCU to osobna droga (`restore_inplace`) - wyłącznie dla commitu zapisanego
    w miejscu, z operacją w dzienniku `inplace_op` (astra Z12): tylko wtedy przerwane cofnięcie ma
    materiał odzysku. Stare backupy tekstowe i commity atomowe cofają się tu, atomowo.
    `replace_guard` = straż podmiany jak w `write_changes` (odmowa → 'blocked', plik nietknięty).

    WERYFIKACJA JAK W ZAPISIE (AR-8): plik tymczasowy FITS jest czytany PRZED podmianą (nieczytelny
    nie zastąpi oryginału), a odczyt po `os.replace` musi dać hash tego, co zapisaliśmy
    (`_after_replace`). Awaria odczytu albo rozjazd po podmianie → 'failed' Z `backup_text`
    i powodem „PODMIENIONY": plik już niesie przywrócony nagłówek, a baza go nie zna - dawniej
    'failed' bez tej prawdy (odczyt padł) albo 'applied' z re-synciem pliku, którego nagłówka nikt
    nie porównał z zapisanym (rozjazd).

    COFNIĘCIE BAJTOWE (AR-19): koperta `RegionBackup`, której region pasuje do bieżącego układu
    pliku (`_plan_przywrocenia`: ten sam początek nagłówka, te same karty układu danych FITS / te
    same adresy bloków XISF), wraca BAJT W BAJT - plik tymczasowy = bieżący plik z regionem backupu
    w miejscu bieżącego nagłówka, bez parsowania i serializacji. `byte_exact` wyniku: `True`, gdy
    sha1 złożonego pliku == sha1 sprzed commitu (`RegionBackup.file_sha1`), `None`, gdy backup go
    nie niesie. Backup tekstowy albo układ, który się nie zgadza → droga SEMANTYCZNA jak dotąd
    (nagłówek odtworzony z treści, astropy / `build_xisf_header_region`), `byte_exact=False`
    i powód „cofnięte semantycznie".
    Pod blokadą i z podmianą systemową jak `write_changes` (AR-18).

    ŚLAD COFNIĘCIA (AR-182, 0044): `persist_result(_PrzygotowaneCofniecie)` - gdy podany - utrwala
    w bazie wynik, który podmiana za chwilę położy pod ścieżką (sha1 i rozmiar pliku tymczasowego
    z aktu jego zapisu, nagłówek), plik zastany pod blokadą (sha1 z tego samego przebiegu składania;
    droga semantyczna FITS - jeden pełny odczyt uchwytu więcej) i nazwy kopii wypartej oraz pliku
    tymczasowego (AR-127) - PRZED podmianą, jak backup zapisu. Porażka → 'failed', plik nietknięty.
    Ponowienie rozpozna po nim własny wynik także wtedy, gdy nie jest plikiem sprzed commitu.

    ZMIANA OD COMMITU: `expect_file_sha1` = sha1 wersji zapisanej przez commit
    (`replace_intent.prepared_sha1`). Plik zastany z innym sha1 zmienił się poza nagłówkiem od
    commitu - cofnięcie idzie (nagłówek wraca, zmiana zostaje w pliku, nikt jej nie traci), a powód
    mówi to wprost (`undo_outside_changed`) zamiast „cofnięte semantycznie” artefaktu serializacji."""
    if _is_raw(path):
        return WriteResult("blocked", _RAW_READ_ONLY, None)
    path = os.fspath(path)
    xisf = _is_xisf(path)
    tmp: str | None = None
    zachowaj_tmp = False
    written_hash = None
    try:
        env = RegionBackup.decode(header_text)
        with _exclusive(path) as fh:
            plan = _plan_przywrocenia(path, fh, env, expected_hash) if env is not None else None
            if isinstance(plan, WriteResult):
                return plan
            if plan is not None:
                czesci, odcisk = plan
                # sha1 pliku zastanego liczy ten sam przebieg po ogonie (jedyna część bajtowa to
                # region koperty w miejscu bieżącego nagłówka) - bez drugiego odczytu.
                tmp, sha1_tmp, sha1_zrodla = _zloz_plik_tymczasowy(path, fh, czesci,
                                                                   oryginal_region=odcisk.region)
                # Plik tymczasowy czytany TĄ SAMĄ formułą co skan, zanim zastąpi oryginał - region
                # backupu ma się czytać nagłówkiem, który backup opisuje.
                written_hash = (scan.read_xisf_meta_full(tmp) if xisf
                                else scan.read_fits_meta(tmp)).header_hash
                if written_hash != env.pre_hash:
                    raise ValueError("region backupu w bieżącym pliku czyta się innym nagłówkiem "
                                     "niż zapisany w backupie - plik nietknięty")
                bajtowo = None if env.file_sha1 is None else sha1_tmp == env.file_sha1
                nota = {True: None, None: _NOTA_BAJTOWO_BEZ_PLIKU,
                        False: _NOTA_SEMANTYCZNIE_POZA_NAGLOWKIEM}[bajtowo]
            else:
                tekst = env.header_text() if env is not None else header_text
                semantyczny = (_xisf_semantyczny(path, fh, tekst, expected_hash) if xisf
                               else _fits_semantyczny(path, fh, tekst, expected_hash))
                if isinstance(semantyczny, WriteResult):
                    return semantyczny
                tmp, written_hash, odcisk, sha1_tmp, sha1_zrodla = semantyczny
                bajtowo = False
                nota = _NOTA_SEMANTYCZNIE
        if bajtowo is False and expect_file_sha1 is not None and sha1_zrodla != expect_file_sha1:
            nota = _NOTA_ZMIANA_OD_COMMITU
        kopia = _nazwa_kopii(path)
        if persist_result is not None:
            try:
                persist_result(_PrzygotowaneCofniecie(sha1_tmp, os.path.getsize(tmp), written_hash,
                                                      bajtowo, sha1_zrodla, odcisk.size, kopia, tmp))
            except Exception as exc:  # noqa: BLE001 - bez śladu nie podmieniamy
                return WriteResult("failed", _slad_nie_powstal(exc), None)
        uwaga = _podmien(tmp, path, replace_guard, odcisk, kopia=kopia)
        tmp = None
    except _XisfRefusal as ref:
        return WriteResult("blocked", ref.reason, None)
    except repo.InplaceConflict as exc:
        return WriteResult("blocked", _powod_konfliktu(exc.op), None)
    except _PodmianaOdbita as exc:
        return WriteResult("blocked", exc.reason, None)
    except _PodmianaRozdarta as exc:
        zachowaj_tmp = exc.zachowaj_tmp
        return WriteResult("failed", exc.reason, written_hash if exc.zaszla else None,
                           header_text if exc.zaszla else None)
    except Exception as exc:  # noqa: BLE001
        return WriteResult("failed", _blad_systemu(exc), None)
    finally:
        _sprzatnij_tmp(tmp, zachowaj_tmp)
    wynik = _after_replace(path, written_hash, header_text, _dopisz(nota, uwaga))   # T3
    return dataclasses.replace(wynik, byte_exact=bajtowo)


_COFNIETE_SEMANTYCZNIE = "cofnięte semantycznie"
# Noty cofnięcia atomowego o bajtach pliku (AR-19) - z kodem dla okna (AR-148).
_NOTA_BAJTOWO_BEZ_PLIKU = PowodPozycji(
    "nagłówek przywrócony bajt w bajt; całego pliku nie porównano - backup commitu nie niesie sha1 "
    "pliku sprzed zapisu", "undo_bytes_unverified")
_NOTA_SEMANTYCZNIE_POZA_NAGLOWKIEM = PowodPozycji(
    f"{_COFNIETE_SEMANTYCZNIE} - nagłówek przywrócony bajt w bajt, ale plik różni się od stanu "
    f"sprzed commitu poza nagłówkiem (sha1 całego pliku)", "undo_semantic_outside")
_NOTA_SEMANTYCZNIE = PowodPozycji(
    f"{_COFNIETE_SEMANTYCZNIE} - nagłówek odtworzony z treści backupu, bajty pliku inne niż przed "
    f"commitem", "undo_semantic")
# AR-182: plik zastany przez cofnięcie nie jest wersją zapisaną przez commit - zmiana poza
# nagłówkiem od commitu (cudza albo wynik semantycznego cofnięcia nowszego commitu tej lokacji), więc
# zdanie mówi fakt, nie sprawcę.
_NOTA_ZMIANA_OD_COMMITU = PowodPozycji(
    f"{_COFNIETE_SEMANTYCZNIE} - nagłówek przywrócony, ale plik zmienił się poza nagłówkiem od commitu "
    f"(sha1 pliku inny niż zapisany przez commit); ta zmiana zostaje w pliku", "undo_outside_changed")


def _xisf_bloki(xml: bytes) -> list[str]:
    """Adresy bloków `attachment:` nagłówka XISF w kolejności dokumentu - układ danych, który
    region backupu musi dzielić z bieżącym plikiem, żeby wrócić bajt w bajt."""
    root = ET.fromstring(scan.xml_parsable(xml))
    return [e.get("location") for e in root.iter()
            if (e.get("location") or "").startswith("attachment:")]


def _plan_przywrocenia(path: str, fh, env: RegionBackup, expected_hash: str | None):
    """Plan bajtowego przywrócenia koperty `env` pod blokadą (`fh`) → `(części pliku tymczasowego,
    odcisk)` | `WriteResult('blocked')` (bieżący nagłówek ≠ `expected_hash`) | `None` (układ się nie
    zgadza - droga semantyczna). Zgodność układu: FITS - wybrane HDU zaczyna się pod `env.offset`
    i karty układu danych (`_fits_layout`) backupu i bieżącego nagłówka są równe; XISF - region
    `[0, first_attachment)` tej samej długości i te same adresy bloków. Dane bieżącego pliku idą
    do pliku tymczasowego verbatim, region - z backupu."""
    if _is_xisf(path):
        meta = _read_xisf_or_refuse(path)
        if expected_hash is not None and meta.header_hash != expected_hash:
            return WriteResult("blocked", _UNDO_HEADER_CHANGED, None)
        if env.fmt != "xisf" or env.offset != 0 or meta.first_attachment != len(env.region):
            return None
        (hlen,) = struct.unpack("<I", env.region[8:12])
        xml_backupu = env.region[scan.XISF_XML_OFFSET:scan.XISF_XML_OFFSET + hlen]
        if _xisf_bloki(xml_backupu) != _xisf_bloki(meta.xml_bytes):
            return None
        try:
            biezacy = scan.build_xisf_header_region(meta, meta.xml_bytes)
        except ValueError:                 # plik przeczy sam sobie - odmówi droga semantyczna
            return None
        _xisf_region_from_handle(fh, meta, biezacy)
        odcisk = _odcisk(fh, 0, meta.first_attachment)
        return [env.region, (meta.first_attachment, None)], odcisk
    granice = _fits_hdu_bounds(path, expected_hash)
    if isinstance(granice, WriteResult):
        # Granice dzieli plan zapisu w miejscu (nagłówek od stagingu); tu cofnięcie - od commitu.
        if granice.reason is _HEADER_HASH_MISMATCH:
            granice = dataclasses.replace(granice, reason=_UNDO_HEADER_CHANGED)
        return granice
    if isinstance(granice, Fallback) or env.fmt != "fits":
        return None
    hdr, start, data_start, _ = granice
    if start != env.offset:
        return None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        stary = fits.Header.fromstring(env.region.decode("latin-1"))
    # Układ danych porównany bez kolejności kart: astropy przy zapisie commitu przestawia
    # `BZERO`/`BSCALE` (AR-19), a znaczenie bajtów danych niosą wartości, nie kolejność.
    if (sorted(_fits_layout(stary), key=lambda kv: kv[0])
            != sorted(_fits_layout(hdr), key=lambda kv: kv[0])):
        return None
    odcisk = _odcisk(fh, start, data_start - start)
    return [(0, start), env.region, (data_start, None)], odcisk


def _fits_semantyczny(path: str, fh, tekst: str, expected_hash: str | None):
    """Droga semantyczna cofnięcia FITS pod blokadą: nagłówek z tekstu backupu, plik tymczasowy
    z `writeto` astropy przez strumień liczący sha1 (`_zapisz_tymczasowy_fits`, te same bajty co
    zapis do ścieżki) → `(tmp, written_hash, odcisk, sha1 tmp, sha1 pliku zastanego)` |
    `WriteResult('blocked')`. sha1 pliku zastanego (ślad cofnięcia, AR-182) to pełny odczyt uchwytu
    blokady - astropy przepisuje cały plik, więc przebiegu po ogonie do współdzielenia nie ma."""
    tmp = None
    try:
        with fits.open(path, mode="readonly", memmap=False) as hdul:
            index, hdu = scan._select_hdu(hdul)
            current = scan._header_hash(hdu.header)
            if expected_hash is not None and current != expected_hash:
                return WriteResult("blocked", _UNDO_HEADER_CHANGED, None)
            info = hdul.fileinfo(index)
            start, data_start = info["hdrLoc"], info["datLoc"]
            hdu.header = fits.Header.fromstring(tekst)
            fd, tmp = tempfile.mkstemp(suffix=".tmp", dir=os.path.dirname(os.path.abspath(path)))
            os.close(fd)
            strumien = _zapisz_tymczasowy_fits(hdul, tmp)
        written_hash = scan.read_fits_meta(tmp).header_hash
        return (tmp, written_hash, _odcisk(fh, start, data_start - start), strumien.hexdigest(),
                _sha1_uchwytu(fh))
    except BaseException:
        _sprzatnij_tmp(tmp, False)
        raise


def _xisf_semantyczny(path: str, fh, xml_text: str, expected_hash: str | None):
    """Droga semantyczna cofnięcia XISF pod blokadą (backup tekstowy albo inne adresy bloków): region
    złożony z XML-a backupu (`build_xisf_header_region` - ta sama bramka mieszczenia się co zapis,
    wypełnienie po skróceniu wraca jako ZERA) + ogon bieżącego pliku → `(tmp, written_hash, odcisk,
    sha1 tmp, sha1 pliku zastanego)` | `WriteResult('blocked')`. Hash zapisanego XML-a znany bez
    odczytu (D-X-3); oba sha1 liczy ten sam przebieg po ogonie (ślad cofnięcia, AR-182)."""
    meta = _read_xisf_or_refuse(path)
    if expected_hash is not None and meta.header_hash != expected_hash:
        return WriteResult("blocked", _UNDO_HEADER_CHANGED, None)
    xml = xml_text.encode("utf-8")
    try:
        region = scan.build_xisf_header_region(meta, xml)
    except ValueError as exc:
        raise _XisfRefusal(powod_wyjatku(exc)) from exc
    _xisf_region_from_handle(fh, meta, scan.build_xisf_header_region(meta, meta.xml_bytes))
    odcisk = _odcisk(fh, 0, meta.first_attachment)
    tmp, sha1_tmp, sha1_zrodla = _zloz_plik_tymczasowy(
        path, fh, [region, (meta.first_attachment, None)], oryginal_region=odcisk.region)
    return tmp, hashlib.sha1(xml).hexdigest(), odcisk, sha1_tmp, sha1_zrodla


# ============================================================ PISARZ XISF (P6c — łata bajtowa)
# Bliźniak `write_changes`/`write_full_header` dla formatu, który nie zna HDU. Technika: ŁATA
# BAJTOWA (wariant B briefu, D-X-1) — podmieniamy DOKŁADNIE bajty edytowanych wartości, a resztę
# nagłówka, wypełnienie, `reserved` i WSZYSTKIE bloki danych przepisujemy verbatim. Re-serializacja
# przez `ET.tostring()` jest odrzucona: przepisałaby cały nagłówek (prefiksy `ns0:`, zgubione
# komentarze, inna kolejność atrybutów) i diff przestałby być do przejrzenia.
#
# DWA NIEPRZEKRACZALNE: (1) offsety bloków danych są BEZWZGLĘDNE i zapisane w XML-u, więc nagłówek
# po edycji mieści się w rezerwie ALBO operacja to 'blocked' — nigdy trzeciej drogi; (2) `sha1_data`
# (sha1 bajtów attachmentu) MUSI przeżyć zapis, inaczej `_resync` uzna plik za PODMIANĘ TREŚCI
# i ROZDWOI klatkę (nowy frame + osierocony stary z zeznaniem i `object_id`).
# Arytmetyka offsetów żyje WYŁĄCZNIE w `scan.build_xisf_header_region` — pisarz jej nie powtarza.

# Karta ↔ własność `<Property>` (D-X-10). Mapa jest JAWNA i wąska: to dwa fakty, które PixInsight
# trzyma podwójnie, więc zapis samej karty zostawiłby plik SPRZECZNY ze sobą. Reguła przelicza
# wartość karty na wartość własności — `FOCALLEN` jest w MILIMETRACH, a `Instrument:Telescope:
# FocalLength` w METRACH (spec XISF 1.0 §11.5.3.4, typ Float32 - stąd artefakty w rodzaju
# `0.1049999967217445`), więc identyczność bajtów tu nie zachodzi i trzeba liczyć. Mapa jest wąska
# ŚWIADOMIE: inne fakty trzymane podwójnie (APTDIA↔Aperture, też w metrach; EXPTIME↔ExposureTime;
# FILTER↔Filter:Name) NIE są łatane, więc edycja ich karty zostawi plik sprzeczny ze sobą.
_XISF_PROPERTY_TARGETS = {
    "TELESCOP": ("Instrument:Telescope:Name", str),
    "FOCALLEN": ("Instrument:Telescope:FocalLength", lambda v: repr(float(v) / 1000.0)),
    # OBJECT dopisany 2026-08-02 (P6d): PixInsight trzyma nazwę obiektu tak samo podwójnie jak
    # teleskop, więc od chwili, w której writeback sięga gotowych stosów, edycja samej karty
    # zostawiałaby plik sprzeczny ze sobą. Reguła jest tożsamościowa (`str`) — zmierzone na 128
    # realnych stosach: 106 ma kartę, z nich 103 ma też własność i bramka zrozumienia przechodzi
    # 103/103 przy ZERO rozjazdów; 3 nie mają własności i zostają pominięte (D-X-10).
    "OBJECT": ("Observation:Object:Name", str),
}


class _XisfRefusal(Exception):
    """Wewnętrzna ODMOWA pisarza XISF → `WriteResult('blocked', reason)`. Odmowa to nie awaria:
    plik zostaje bajtowo nietknięty, a powód trafia do usera. Osobny typ (nie `ValueError`), żeby
    „nie ruszam, bo nie rozumiem" nigdy nie zlało się z „coś się zepsuło" (to drugie = 'failed').
    Odmowa czytnika `scan` owinięta tym typem niesie GOTOWY powód z kodem (`powod_wyjatku`:
    `scan.XisfFormatError.powod`, AR-158) - pisarz nie składa nowego; `ValueError` bez kodu -
    prozą jak dotąd (granica)."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _read_xisf_or_refuse(path):
    """Wczytaj `XisfMeta` albo ODMÓW. Skarga CZYTNIKA na format (zła sygnatura, ucięty nagłówek,
    niepoprawny XML) to trwała cecha pliku, nie awaria — 'blocked' z powodem, jak reszta bramek
    (§6 pkt 7: „plik nieparsowalny"). `OSError` przepuszczamy: brak pliku / brak uprawnień /
    zerwany SMB to AWARIA ('failed'), bo jutro może się udać, a odmowa sugerowałaby werdykt o pliku."""
    try:
        return scan.read_xisf_meta_full(path)
    except OSError:
        raise
    except scan.XisfFormatError as exc:
        # Odmowa czytnika z kodem (AR-158): kod i parametry jadą do okna, a zdanie PL zostaje
        # dotychczasowym „nieczytelny - Typ: opis" - typem tych odmów przed kodem był `ValueError`.
        powod = powod_wyjatku(exc)
        raise _XisfRefusal(PowodPozycji(f"nagłówek XISF nieczytelny - ValueError: {powod}",
                                        "xisf_unreadable_reader", inner=powod)) from exc
    except Exception as exc:  # noqa: BLE001 — czytnik zgłasza format wieloma typami (w tym ParseError)
        blad = _blad_systemu(exc)
        raise _XisfRefusal(PowodPozycji(f"nagłówek XISF nieczytelny - {blad}", "xisf_unreadable",
                                        detail=blad)) from exc


def _xisf_gates(meta) -> None:
    """Bramki odmowy liczone z PLIKU (D-X-11/13), zanim cokolwiek policzymy z operacji.

    Bramka tożsamości ma bliźniaka w bazie (`macro.resolve_target` czyta
    `frame.sha1_data_uncomputable`) — ta tutaj domyka wywołanie pisarza z pominięciem makra."""
    if meta.keyword_images > 1:
        raise _XisfRefusal(PowodPozycji(
            "karty pod wieloma <Image> - cel zapisu niejednoznaczny (D-X-11)", "xisf_many_images"))
    if meta.image_span is None:
        raise _XisfRefusal(PowodPozycji(
            "tożsamość nieobliczalna (brak obrazu-attachmentu) - zapis rozdwoiłby klatkę (D-X-13)",
            "xisf_no_identity"))


def _xisf_property_patch(meta, keyword, idx, new_text):
    """Wycinek WŁASNOŚCI towarzyszącej karcie (D-X-10) albo `None`, gdy nie ma czego łatać.

    Własność NIEOBECNA → pomijamy: plik, który jej nigdy nie miał, nie jest ze sobą sprzeczny.
    Własność w `location=` albo pusta → odmowa: cel jest realny, więc po zapisie samej karty plik
    ZAPRZECZAŁBY sam sobie.

    BRAMKA ZROZUMIENIA (EXPECT): łatamy własność tylko wtedy, gdy jej BIEŻĄCA wartość jest dokładnie
    tym, co reguła wylicza z BIEŻĄCEJ karty. Zmierzone na archiwum: trzyma na 121/122 plikach
    i 7/7 celów naprawy `ED`; jedyny rozjazd to masterflat z `FOCALLEN=105` i własnością
    `0.1049999967217445` (artefakt Float32). Tam konwencji NIE ROZUMIEMY — bez bramki wpisalibyśmy
    `0.105` i po cichu zmienili semantykę pliku. Bramka trzyma też ZAPIS TOŻSAMOŚCIOWY (§6 pkt 1):
    skoro obecna wartość == reguła(obecna karta), to przepisanie karty jej własną wartością nie
    rusza ani bajtu własności."""
    target = _XISF_PROPERTY_TARGETS.get(keyword)
    if target is None:
        return None
    pid, rule = target
    xml = meta.xml_bytes
    try:
        span = scan.locate_value_span(xml, property_id=pid)
    except scan.XisfTargetMissing:
        return None                                   # własność nieobecna → NIE tworzymy (D-X-10)
    except scan.XisfValueUnreachable as exc:
        raise _XisfRefusal(powod_wyjatku(exc)) from exc
    obecna = xml[span[0]:span[1]]
    stara_karta = next((c.value_raw for c in meta.cards
                        if c.keyword == keyword and c.idx == idx), None)
    if stara_karta is None:                            # lustro kart rozjechane z lokalizatorem
        raise ValueError(f"XISF: karta {keyword}[{idx}] zlokalizowana, ale nieobecna w lustrze kart")
    try:
        z_karty = scan.encode_xisf_value(rule(stara_karta), xml, span)
        nowa = scan.encode_xisf_value(rule(new_text), xml, span)
    except (TypeError, ValueError) as exc:
        blad = _blad_systemu(exc)
        raise _XisfRefusal(PowodPozycji(
            f"własność {pid}: reguła nie liczy się dla {repr(new_text)} ({blad})", "xisf_prop_rule",
            prop=pid, value=repr(new_text), detail=blad)) from exc
    if z_karty != obecna:
        raise _XisfRefusal(PowodPozycji(
            f"własność {pid} = {obecna.decode('utf-8', 'replace')}, a z karty {keyword}="
            f"{repr(stara_karta)} wychodzi {z_karty.decode('utf-8', 'replace')} - konwencji tego "
            f"pliku NIE ROZUMIEM, więc jej nie ruszam", "xisf_prop_mismatch", prop=pid,
            current=obecna.decode('utf-8', 'replace'), keyword=keyword, card=repr(stara_karta),
            derived=z_karty.decode('utf-8', 'replace')))
    return (*span, nowa)


def _xisf_add_patch(meta, keyword: str, new_text: str, comment) -> tuple[int, int, bytes]:
    """Wycinek ZEROWEJ długości `(offset, offset, bajty)` = dopisanie karty (P6d, domknięcie D-X-12).

    Trzy bramki odmowy PRZED złożeniem elementu — każda pilnuje czegoś innego:

    1. **Karta już jest** → odmowa. `add` na istniejącej karcie dopisałby DRUGĄ o tej samej nazwie,
       a wtedy `locate_value_span(idx=0)` i parser wskazywałyby różne wystąpienia. Kto chce zmienić
       wartość, woła `set`.
    2. **Własność zmapowana ISTNIEJE, a karty nie ma** → odmowa. To lustro D-X-10 od drugiej strony:
       plik zeznaje o obiekcie własnością, więc dopisanie karty o INNEJ treści uczyniłoby go
       sprzecznym, a bramki zrozumienia nie ma jak postawić — nie istnieje karta, z której reguła
       miałaby policzyć wartość oczekiwaną. Zmierzone: z 22 stosów bez karty `OBJECT` własność
       ma ZERO, więc ta bramka dziś nie odsiewa nic i ma tak zostać.
    3. Reszta (brak kart, brak wzorca w apostrofach, obce atrybuty wzorca) → `build_fits_keyword_
       element` odmawia własnymi słowami; tu tylko mapujemy `ValueError` na 'blocked', bo to
       wszystko są cechy PLIKU, nie usterki kodu.

    Własności NIE dopisujemy razem z kartą (D-X-10 „nieobecna → nie tworzymy"): plik, który jej
    nigdy nie miał, nie jest ze sobą sprzeczny, a tworzenie `<Property>` to wybór miejsca i typu
    — osobna klasa ryzyka niż kopia sąsiedniej karty."""
    xml = meta.xml_bytes
    try:
        scan.locate_value_span(xml, keyword=keyword, idx=0)
    except scan.XisfTargetMissing:
        pass
    else:
        raise _XisfRefusal(_karta_juz_jest(keyword))       # ten sam kod co FITS i podgląd (AR-256)
    target = _XISF_PROPERTY_TARGETS.get(keyword)
    if target is not None:
        try:
            scan.locate_value_span(xml, property_id=target[0])
        except scan.XisfTargetMissing:
            pass
        except scan.XisfValueUnreachable as exc:
            raise _XisfRefusal(powod_wyjatku(exc)) from exc
        else:
            raise _XisfRefusal(PowodPozycji(
                f"plik nie ma karty {keyword}, ale ma własność {target[0]} - dopisanie karty "
                f"mogłoby mu zaprzeczyć, a bramki zrozumienia nie ma na czym postawić",
                "xisf_prop_without_card", keyword=keyword, prop=target[0]))
    try:
        offset, blob = scan.build_fits_keyword_element(
            xml, keyword=keyword, value=new_text, comment=comment)
    except ValueError as exc:                 # w tym XisfTargetMissing/Unreachable (podklasy)
        raise _XisfRefusal(powod_wyjatku(exc)) from exc
    return offset, offset, blob


def _xisf_patches(meta, ops: list[WriteOp]) -> list[tuple[int, int, bytes]]:
    """Komplet wycinków do podmiany `[(start, end, bajty)]`, liczonych na ORYGINALNYM `xml_bytes` —
    dlatego najpierw lokalizujemy wszystko, a plik składamy JEDEN raz (adresy nie mogą się przesuwać
    pod własną łatą).

    `add` idzie osobną drogą (`_xisf_add_patch`, P6d) i daje wycinek ZEROWEJ długości — wstawkę,
    nie podmianę. `_xisf_apply` przyjmuje ją bez zmian, bo asercja niezachodzenia porównuje
    `start < last`, a wstawka ma `start == end`. D-X-12 („dodawanie kart poza P6") jest tym
    DOMKNIĘTE, nie obejście: element nie jest składany od zera, tylko kopiowany z sąsiedniej karty
    tego samego pliku.

    `set` na karcie NIEOBECNEJ zostaje odmową — w FITS astropy dopisałby ją po cichu, a tutaj
    założenie karty ma być decyzją wołającego wypowiedzianą wprost ('add'), nie skutkiem ubocznym
    literówki w keywordzie. Wartość idzie do pliku jako TEKST bez rzutowania: XISF trzyma wartości
    tekstem, a karty XISF mają `value_type` zawsze `'str'` (D-X-4)."""
    xml = meta.xml_bytes
    patches: list[tuple[int, int, bytes]] = []
    for op in ops:
        if op.op not in ("set", "add"):
            raise _XisfRefusal(PowodPozycji(
                f"operacja '{op.op}' na XISF nie istnieje - writeback zna 'set' i 'add'",
                "xisf_bad_op", op=op.op))
        keyword, idx = op.keyword.strip().upper(), op.idx or 0
        new_text = str(op.value)
        if op.op == "add":
            patches.append(_xisf_add_patch(meta, keyword, new_text, op.comment))
            continue
        ile = sum(1 for c in meta.cards if c.keyword == keyword)
        if op.idx is None and ile > 1:
            raise _XisfRefusal(_wymagany_idx(keyword))        # jak FITS i podgląd (AR-256)
        try:
            span = scan.locate_value_span(xml, keyword=keyword, idx=idx)
        except scan.XisfTargetMissing as exc:
            if ile and not 0 <= idx < ile:     # karta jest, wystąpienia `idx` nie - jak FITS i podgląd;
                # wystąpienie, które JEST, a nie ma atrybutu `value=`, zostaje przy powodzie czytnika
                raise _XisfRefusal(_brak_wystapienia(keyword, idx, ile)) from exc
            brak = powod_wyjatku(exc)          # zdanie czytnika `scan` z kodem (AR-158)
            raise _XisfRefusal(PowodPozycji(
                f"{brak} - 'set' nie zakłada karty; dopisanie idzie przez 'add' (P6d)",
                "xisf_set_missing", detail=brak)) from exc
        patches.append((*span, scan.quote_fits(new_text, xml[span[0]:span[1]])))
        if op.comment is not None:
            try:
                cspan = scan.locate_value_span(xml, keyword=keyword, idx=idx, attr="comment")
            except scan.XisfTargetMissing as exc:
                brak = powod_wyjatku(exc)      # zdanie czytnika `scan` z kodem (AR-158)
                raise _XisfRefusal(PowodPozycji(f"{brak} - dodanie atrybutu poza P6 (D-X-12)",
                                                "xisf_attr_missing", detail=brak)) from exc
            patches.append((*cspan, scan.encode_xisf_value(op.comment, xml, cspan)))
        prop = _xisf_property_patch(meta, keyword, idx, new_text)
        if prop is not None:
            patches.append(prop)
    return patches


def _xisf_apply(xml: bytes, patches) -> bytes:
    """Złóż nowy nagłówek z wycinków — rosnąco po `start`, z asercją NIEZACHODZENIA. Dwa wycinki na
    tych samych bajtach znaczyłyby, że adresowanie się rozjechało, a wynik zależałby od kolejności
    (`ValueError` → 'failed', nigdy cicha wygrana ostatniego)."""
    out, last = [], 0
    for start, end, blob in sorted(patches):
        if start < last:
            raise ValueError(f"XISF: wycinki łaty zachodzą na siebie ({start} < {last})")
        out.append(xml[last:start])
        out.append(blob)
        last = end
    out.append(xml[last:])
    return b"".join(out)


def _xisf_backup_text(meta) -> str:
    """Backup do undo = ORYGINALNY XML jako tekst, z asercją ODWRACALNOŚCI zrobioną PRZED zapisem
    (D-X-9). `header_backups.header_text` to kolumna TEKSTOWA, więc nagłówek, który nie przechodzi
    round-tripu bajty→tekst→bajty, po undo odtworzyłby INNY plik. Zapis bez odwracalnego backupu
    jest gorszy niż brak zapisu → odmowa."""
    try:
        text = meta.xml_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        blad = _blad_systemu(exc, z_typem=False)
        raise _XisfRefusal(PowodPozycji(
            f"nagłówek nie jest tekstem UTF-8 - backup do undo niemożliwy ({blad})", "xisf_not_utf8",
            detail=blad))
    if text.encode("utf-8") != meta.xml_bytes:
        raise _XisfRefusal(PowodPozycji(
            "nagłówek nie przechodzi round-tripu bajty→tekst→bajty - backup do undo byłby "
            "nieodwracalny", "xisf_no_roundtrip"))
    return text


def _xisf_expected_cards(meta, ops) -> list[tuple]:
    """Karty, które nagłówek MA mieć po łacie, jako `(keyword, idx, value_raw, comment)` - policzone
    z kart SPRZED łaty i z operacji, a NIE z bajtów łaty. Tylko wtedy porównanie z kartami
    odczytanymi z nowego XML-a sprawdza łatę, zamiast powtarzać ją drugi raz.

    Wartość w postaci, w jakiej odda ją czytnik: w karcie tekstowej (apostrofy w oryginale) bez
    końcowych spacji - FITS 4.0 §4.2.1.1 ma je za nieznaczące i czytnik je zdejmuje; w karcie gołej
    dosłownie. Karta dopisana (`add`) jest zawsze tekstowa (wzorzec w apostrofach) i staje NA KOŃCU
    bloku kart. `set` bez komentarza komentarza nie rusza."""
    want = [[c.keyword, c.idx, c.value_raw, c.comment] for c in meta.cards]
    by_addr = {(c[0], c[1]): c for c in want}
    for op in ops:
        keyword, idx, text = op.keyword.strip().upper(), op.idx or 0, str(op.value)
        if op.op == "add":
            want.append([keyword, 0, text.rstrip(), op.comment or None])
            continue
        start, end = scan.locate_value_span(meta.xml_bytes, keyword=keyword, idx=idx)
        orig = meta.xml_bytes[start:end]
        tekstowa = len(orig) >= 2 and orig.startswith(b"'") and orig.endswith(b"'")
        card = by_addr[(keyword, idx)]
        card[2] = text.rstrip() if tekstowa else text
        if op.comment is not None:
            card[3] = op.comment or None
    return [tuple(c) for c in want]


def _xisf_verify(meta, ops, patches, new_xml: bytes) -> None:
    """WERYFIKACJA nowego nagłówka PRZED plikiem tymczasowym - trzy pytania, każde o co innego:

    1. **Łata nie wnosi bajtu nielegalnego w XML 1.0** (spec §9.5). Pytamy o WYCINKI, nie o cały
       nagłówek: zastany bajt sterujący w cudzej treści (archiwum ma plik z 0x07 w historii
       przetwarzania) nie jest winą łaty i nie blokuje zapisu. Wartości i komentarze przeszły już
       `card_violation`, więc ta bramka łapie to, czego tamta nie widzi - bajty skopiowane z pliku
       przy `add` (wcięcie, wzorzec karty).
    2. **Nowy nagłówek się parsuje.** Z neutralizacją `scan.xml_parsable`, jak w czytniku - z tego
       samego powodu co pkt 1 (zastanego 0x07 nie liczymy łacie).
    3. **Round-trip kart:** karty wyłuskane z nowego XML-a TĄ SAMĄ funkcją co skan
       (`scan.xisf_cards`) == karty oczekiwane po łacie (`_xisf_expected_cards`). Łapie łatę
       w złym miejscu, escape, który zmienia sens, wstrzykniętą albo zgubioną kartę.
    4. **`FITSKeyword` nie jest dzieckiem `FITSKeyword`** (AR-6). Round-trip kart tego nie widzi:
       `xisf_cards` chodzi po CAŁYM drzewie, więc karta wstawiona do wnętrza innej daje te same
       karty w tej samej kolejności. Liczymy zagnieżdżenia WNIESIONE przez łatę (więcej niż
       w nagłówku sprzed łaty) - z tego samego powodu co w pkt 1.

    Każde „nie" to `ValueError` → 'failed', nie 'blocked' - ten sam kontrakt co guard
    `locate_value_span`: pisarz złożył nagłówek, który nie mówi tego, co zamierzał, a to usterka
    do zbadania, nie werdykt o pliku (plik i tak zostaje nietknięty - pliku tymczasowego jeszcze
    nie ma). Treść łamiącą reguły karty odsiewa wcześniej `card_violation` jako 'blocked'."""
    for start, end, blob in patches:
        if scan.xml_parsable(blob) != blob:
            raise ValueError(f"XISF: łata wnosi bajt nielegalny w XML 1.0 (wycinek {start}:{end})")
    try:
        root = ET.fromstring(scan.xml_parsable(new_xml))
    except ET.ParseError as exc:
        raise ValueError(f"XISF: nagłówek po łacie nie jest poprawnym XML 1.0 ({exc})") from exc
    got = [(c.keyword, c.idx, c.value_raw, c.comment) for c in scan.xisf_cards(root)]
    want = _xisf_expected_cards(meta, ops)
    if got != want:
        rozjazd = next(((g, w) for g, w in zip(got, want) if g != w),
                       (f"{len(got)} kart", f"{len(want)} kart"))
        raise ValueError(f"XISF: karty odczytane po łacie rozjechały się z oczekiwanymi "
                         f"({rozjazd[0]!r} != {rozjazd[1]!r})")
    przed = _xisf_nested_keywords(ET.fromstring(scan.xml_parsable(meta.xml_bytes)))
    if _xisf_nested_keywords(root) > przed:
        raise ValueError("XISF: łata zagnieżdża <FITSKeyword> w innej karcie (AR-6)")


def _xisf_nested_keywords(root) -> int:
    """Liczba kart `<FITSKeyword>` leżących WEWNĄTRZ innej karty - warunek pkt 4 `_xisf_verify`."""
    karty = [e for e in root.iter() if scan._local_name(e.tag) == "FITSKeyword"]
    return sum(1 for k in karty for e in k.iter() if e is not k
               and scan._local_name(e.tag) == "FITSKeyword")


def _xisf_prepare(path: str, ops: list[WriteOp], expected_hash: str | None):
    """Wszystko, co pisarz XISF liczy PRZED dotknięciem pliku, wspólne dla drogi atomowej
    (`write_xisf_changes`) i zapisu w miejscu (`_xisf_inplace_plan`) - jedna kolejność bramek,
    więc obie drogi odmawiają tych samych plików tymi samymi słowami.

    Zwraca `(meta, new_xml, backup_text, region)`; odmowa to `_XisfRefusal` (w tym niezgodny
    `header_hash` - ten sam powód co w FITS, `_HEADER_HASH_MISMATCH`), awaria - każdy inny wyjątek."""
    meta = _read_xisf_or_refuse(path)
    if expected_hash is not None and meta.header_hash != expected_hash:
        raise _XisfRefusal(_HEADER_HASH_MISMATCH)
    _xisf_gates(meta)
    powod = _ops_violation(ops, lambda op: op.op == "add")   # `set` nie zakłada karty (niżej)
    if powod is not None:
        raise _XisfRefusal(powod)
    patches = _xisf_patches(meta, ops)
    new_xml = _xisf_apply(meta.xml_bytes, patches)
    _xisf_verify(meta, ops, patches, new_xml)      # §9.5 + round-trip: PRZED jakimkolwiek zapisem
    backup_text = _xisf_backup_text(meta)          # D-X-9: PRZED mutacją, nie przy undo
    try:
        region = scan.build_xisf_header_region(meta, new_xml)      # D-X-1/2
    except ValueError as exc:                      # nie mieści się / plik przeczy sam sobie
        raise _XisfRefusal(powod_wyjatku(exc)) from exc
    return meta, new_xml, backup_text, region


def write_xisf_changes(path, ops: list[WriteOp], expected_hash: str | None, *,
                       persist_backup: Callable[[str, str, _Zamiar], None] | None = None,
                       replace_guard=None,
                       confirm_backup: Callable[[], None] | None = None) -> WriteResult:
    """Łata bajtowa nagłówka XISF - bliźniak `write_changes` z tym samym kontraktem `WriteResult`.

    Kolejność (brief §5, `_xisf_prepare`): odczyt → kontrola `header_hash` (≠ → 'blocked', NIE
    pisze) → bramki D-X-11/13 → REGUŁY KARTY (`card_violation`, spec §11.6) → lokalizacja
    i podmiana wycinków (karta + zmapowana własność + komentarz) → WERYFIKACJA nowego XML-a
    (`_xisf_verify`: §9.5 i round-trip kart) → round-trip backupu (D-X-9) → BRAMKA MIESZCZENIA SIĘ
    (D-X-2) → plik tymczasowy (nowy region + ogon verbatim od pierwszego bloku danych) i backup
    (`RegionBackup` całego regionu `[0, first_attachment)` z sha1 całego pliku z tego samego
    przebiegu po ogonie - AR-19) → backup utrwalony przez `persist_backup` PRZED podmianą (Z3) →
    podmiana systemowa z rewalidacją pliku wypartego (AR-18) → weryfikacja po podmianie
    (`_after_replace`: `post_hash` z ZAPISANEGO pliku == sha1 złożonego XML-a). Wszystko do backupu
    włącznie pod blokadą `_exclusive`, jak w `write_changes`.

    Odmowa ('blocked') zostawia plik bajtowo nietknięty - wszystkie bramki liczą się PRZED
    stworzeniem pliku tymczasowego. Awaria ('failed') to każdy inny wyjątek, w tym rozejście się
    skanu bajtowego z parserem (guard `locate_value_span`) i nieudana weryfikacja nowego XML-a: tam
    nie wiemy, co byśmy zapisali, więc nie piszemy, ale to usterka do zbadania, nie polityka odmowy."""
    path = os.fspath(path)
    tmp: str | None = None
    zachowaj_tmp = False
    written_hash = backup_text = None
    try:
        with _exclusive(path) as fh:
            meta, new_xml, _, region = _xisf_prepare(path, ops, expected_hash)
            _xisf_region_from_handle(fh, meta, scan.build_xisf_header_region(meta, meta.xml_bytes))
            odcisk = _odcisk(fh, 0, meta.first_attachment)
            # Header_hash XISF to sha1 bajtów XML (D-X-3), a pisarz zapisuje je 1:1 - więc hash
            # tego, co zapiszemy, znamy bez odczytu, a odczyt (T3) ma go tylko potwierdzić.
            written_hash = hashlib.sha1(new_xml).hexdigest()
            # sha1 pliku tymczasowego liczy złożenie w tym samym przebiegu (Z13) - bez drugiego
            # odczytu; rozmiar ze `stat`.
            tmp, sha1_tmp, file_sha1 = _zloz_plik_tymczasowy(
                path, fh, [region, (meta.first_attachment, None)], oryginal_region=odcisk.region)
            backup_text = RegionBackup("xisf", 0, odcisk.region, odcisk.size, odcisk.ino,
                                       meta.header_hash, file_sha1).encode()
        zamiar = _zamiar(path, tmp, sha1_tmp, os.path.getsize(tmp))
        if persist_backup is not None:
            try:
                persist_backup(backup_text, written_hash, zamiar)
            except Exception as exc:  # noqa: BLE001 - bez backupu nie podmieniamy
                return WriteResult("failed", _backup_nie_powstal(exc), None)
        uwaga = _podmien(tmp, path, replace_guard, odcisk, confirm_backup,
                         zamiar=zamiar if persist_backup is not None else None)
        tmp = None
    except _XisfRefusal as ref:
        return WriteResult("blocked", ref.reason, None)
    except repo.InplaceConflict as exc:                    # straż odbiła podmianę - plik nietknięty
        return WriteResult("blocked", _powod_konfliktu(exc.op), None)
    except _PodmianaOdbita as exc:                         # cudza zmiana wróciła na miejsce
        return WriteResult("blocked", exc.reason, None)
    except _WypartaDoPowrotu as exc:                       # powrót zrobi automat orkiestracji
        return WriteResult("failed", exc.reason, None, code=CODE_POWROT_WYPARTEJ)
    except _PodmianaRozdarta as exc:
        zachowaj_tmp = exc.zachowaj_tmp
        return WriteResult("failed", exc.reason, written_hash if exc.zaszla else None,
                           backup_text if exc.zaszla else None)
    except Exception as exc:  # noqa: BLE001 - raport zamiast wyjątku w warstwie zapisu
        return WriteResult("failed", _blad_systemu(exc), None)
    finally:
        _sprzatnij_tmp(tmp, zachowaj_tmp)
    return _after_replace(path, written_hash, backup_text, uwaga)


def write_xisf_full_header(path, header_text: str, expected_hash: str | None) -> WriteResult:
    """Przywróć nagłówek XISF z backupu (ścieżka undo, D-X-9) - to samo co `write_full_header`
    dla pliku `.xisf` (zob. tam). Nazwa zostaje dla wołających."""
    return write_full_header(path, header_text, expected_hash)


# ============================================================ ZAPIS W MIEJSCU (O5, 2026-09-26)
# Decyzja usera 2026-09-26 (wariant O5, ujednolicenie kart `OBJECT`): podmiana SAMEGO nagłówka
# w miejscu, zamiast przepisywania całego pliku przez plik tymczasowy i `os.replace`. Powód jest
# ilościowy: dla populacji ujednolicenia droga atomowa to ~420 GB zapisu po SMB, a `os.replace`
# zrywa twarde dowiązania projekcji `_WBPP` (stary nagłówek zostaje w projekcji; `st_nlink` po SMB
# kłamie, dowodem tożsamości pliku jest `st_ino`). Zapis w miejscu zachowuje `st_ino`, nie dotyka
# danych i pisze kilkadziesiąt bajtów.
#
# Ceną jest ATOMOWOŚĆ - przerwa w trakcie zapisu może zostawić nagłówek rozdarty. Stąd kolejność
# inna niż w drodze atomowej, każdy krok z własnym testem:
#   0. BLOKADA (`_exclusive`): uchwyt otwarty przez `CreateFileW` z trybem współdzielenia
#      `FILE_SHARE_READ` - bez `FILE_SHARE_WRITE` i `FILE_SHARE_DELETE`. Od tej chwili do końca
#      weryfikacji nikt inny nie otworzy pliku do zapisu ani go nie podmieni/nie usunie (odmowa
#      systemu), a proces, który JUŻ trzyma plik do zapisu, sprawia, że blokada się nie uda - wtedy
#      krótki ponów z przerwą (błąd współdzielenia bywa przejściowy: antywirus, indeksowanie), a po
#      nim 'failed' bez zapisu. Czytać plik wolno dalej, także nam (astropy, weryfikacja).
#   1. PLAN pod blokadą: kontrola `header_hash`, reguły karty (`card_violation`), nowy region
#      o TEJ SAMEJ długości, weryfikacja łaty przed zapisem. REGION STARY CZYTANY Z UCHWYTU BLOKADY
#      sam przechodzi kontrolę oczekiwanego hasha, granic nagłówka (karta `END` w ostatnim bloku
#      regionu) i układu danych - offsety z odczytu parsera nie są przyjmowane na wiarę.
#   2. DZIENNIK w bazie (`journal.begin`) PRZED pierwszym bajtem zapisu, jedną transakcją:
#      backup `RegionBackup` (surowy region, do undo) i operacja `inplace_op` (0022) w fazie
#      `writing` - region stary i planowany wynikowy, zakres zapisu, rozmiar i `st_ino` pliku.
#      Porażka to 'failed' z plikiem nietkniętym. Operacja otwarta izoluje lokację od skanu.
#   3. JEDEN `write` jednego spójnego zakresu (od pierwszego do ostatniego różnego bajtu regionu)
#      + `flush` + `os.fsync`.
#   4. WERYFIKACJA (odczyt KLIENTA - osobny uchwyt, ale ta sama maszyna i jej pamięć podręczna;
#      niezależnej kontroli po stronie NAS to nie zastępuje, zob. `scripts/kontrola_pilotazu.py`):
#      rozmiar pliku, bajty regionu, odcisk próbek danych, `header_hash` formułą skanu. Zgodna →
#      faza `written`, rozjazd albo przerwa → `unverified`. Nieutrwalone przejście fazy to operacja
#      NIEUKOŃCZONA ('failed', izolacja zostaje), nie dopisek do sukcesu.
#   5. DOKOŃCZENIE (`_dokoncz`, znów pod blokadą): region na dysku == wynik operacji, brak nowszej
#      operacji lokacji, KONTROLA DANYCH i re-sync bazy → jedna transakcja: faza `synced`, wpisy
#      stagingu operacji 'applied', nagrobek ręki (`repo.finish_inplace_op`). Do tej chwili lokacja
#      jest izolowana; porażka zostawia `written` i drogę ponowienia (`finish_inplace`), a nieudana
#      kontrola danych - drogę powrotu (`recover_torn` → `_powrot_z_written`).
#
# DANE: zakres zapisu leży w regionie nagłówka z konstrukcji, a pisany jest jednym `write` od adresu
# wewnątrz regionu - jedyne dane, które usterka arytmetyki mogłaby nadpisać, to bajty TUŻ ZA
# regionem, a zapis poza koniec pliku zmieniłby jego rozmiar. Stąd próbki: 64 KiB przed regionem,
# 64 KiB od początku danych, 64 KiB końca pliku + rozmiar. Próbki nie widzą reszty pliku (drugie
# HDU FITS, kolejny obraz albo załącznik XISF), a `sha1_data` obejmuje tylko wybrane HDU / pierwszy
# obraz - więc PEŁNY DOWÓD daje kontrola danych dokończenia (astra, 2026-09-27): sha1 pliku
# z PODSTAWIONYM starym regionem operacji == kotwica sprzed zapisu (`FileAnchor`,
# `_resync(kontrola=)`). Kotwicę bazy sprawdza pisarz pod blokadą PRZED pierwszym bajtem: brak
# (`NULL`), inny `mtime` pliku niż w bazie albo tryb ścisły (pilotaż) → pełny odczyt uchwytu; sha1
# inny niż w bazie → 'blocked' (baza nie opisuje tego pliku). Kotwica idzie do operacji
# (`inplace_op.anchor_sha1`, 0023) - niezmienna, w odróżnieniu od `location.file_sha1`, którą
# przestawia każdy zapis faktów kopii.
#
# ODZYSK ROZDARTEGO NAGŁÓWKA (`recover_region`, orkiestracja `recover_torn`): wyłącznie dla
# OTWARTEJ operacji z dziennika i wyłącznie wtedy, gdy region pod blokadą jest stanem pośrednim TEJ
# operacji (każdy bajt zakresu zapisu = stary albo nowy, poza zakresem = stary) w tym samym pliku.
# Bez parsowania bieżącego nagłówka. Zgodność rozmiaru i próbek nie jest dowodem (astra Z11).
#
# UNDO W MIEJSCU (`restore_inplace`) wyłącznie dla commitu zapisanego w miejscu, z operacją
# w dzienniku, na tym samym pliku i z CAŁYM regionem równym regionowi wynikowemu commitu (Z12/Z13);
# każde inne undo idzie drogą atomową (`write_full_header`).
#
# SPADEK NA DROGĘ DOTYCHCZASOWĄ (`Fallback`) wyłącznie PRZED jakimkolwiek zapisem i backupem:
# FITS, gdy łata nie mieści się w jednym 80-bajtowym rekordzie, gdy karta `set` występuje więcej
# niż raz, gdy dopisanie nie ma w nagłówku miejsca (pusta karta na końcu albo wolny rekord za `END`
# w ostatnim bloku 2880 B) albo gdy zapis zmieniłby RODZAJ wartości karty (tekst, logika, liczba;
# karta liczbowa i logiczna tego samego rodzaju idzie w miejscu - AR-261). FITS z kartą
# `CHECKSUM`/`DATASUM` to ODMOWA ('blocked'), nie spadek: zapis unieważniłby sumę, a pisarz jej nie
# przelicza - ta sama odmowa stoi na drodze atomowej (`_odmowa_sumy`, AR-166), więc spadek niczego
# by nie zmienił. Tak samo odmowa ŁATY (`add` karty, która już jest, typ, wystąpienie - AR-256,
# AR-257): przebieg próbny `_apply_op` w planie odmawia od razu tym samym powodem. XISF spadku NIE MA: region
# nagłówka XISF ma stały rozmiar w obu drogach, więc brak rezerwy odmawia tak samo tu, jak w pliku
# tymczasowym.

_PROBE_BYTES = 1 << 16    # próbka: przed regionem, początek danych, koniec pliku (po 64 KiB)
# Karty układu danych FITS (+ `NAXISn`): przywrócenie w miejscu wymaga, żeby były TE SAME - inaczej
# te same bajty danych znaczyłyby co innego. Zapis w miejscu ich nie łata w ogóle (tylko karty
# zwykłe), więc dla commitu to asercja, a dla undo - bramka.
_FITS_LAYOUT_KEYWORDS = frozenset({"SIMPLE", "XTENSION", "BITPIX", "NAXIS", "EXTEND", "PCOUNT",
                                   "GCOUNT", "GROUPS", "BZERO", "BSCALE", "BLANK"})
# Karty bez wartości albo z wartością, której układ nie jest „keyword = 'tekst' / komentarz".
_FITS_NOT_INPLACE = frozenset({"", "COMMENT", "HISTORY", "CONTINUE", "END"})
# Sumy kontrolne FITS (standard 4.0, dodatek J): zmiana bajtu nagłówka unieważnia CHECKSUM.
_FITS_SUM_KEYWORDS = ("CHECKSUM", "DATASUM")


def _odmowa_sumy(hdr) -> PowodPozycji | None:
    """ODMOWA SUMY KONTROLNEJ - jedna reguła dla obu dróg zapisu FITS (AR-166): `write_changes`
    i `_fits_inplace_plan` pytają o nią w tym samym miejscu kolejki bramek (po kontroli
    `header_hash` i regułach karty). Nagłówek z kartą `CHECKSUM`/`DATASUM` → powód z nazwami kart
    tego pliku; podgląd przewiduje ją z bazy (`card_rules.bramka_sumy`)."""
    sumy = [k for k in _FITS_SUM_KEYWORDS if k in hdr]
    if not sumy:
        return None
    return PowodPozycji(f"FITS z sumą kontrolną ({', '.join(sumy)}) - zapis nagłówka unieważniłby "
                        f"ją, a pisarz jej nie przelicza", "checksum_present", sums=sumy)
_FITS_END_RECORD = b"END" + b" " * 77
# Blokada: przerwy między próbami otwarcia przy błędzie współdzielenia (32) / blokady (33).
_LOCK_RETRY_DELAYS = (0.2, 0.5, 1.0, 2.0)
_LOCK_TRANSIENT = frozenset({32, 33})
_BACKUP_MAGIC = "HORREUM-REGION/1 "


@dataclasses.dataclass(frozen=True)
class Fallback:
    """Plik nie nadaje się do zapisu w miejscu - wołający idzie drogą dotychczasową. Powstaje
    WYŁĄCZNIE przed jakimkolwiek zapisem i przed backupem (plik nietknięty, baza nietknięta)."""
    reason: str


@dataclasses.dataclass(frozen=True)
class RegionBackup:
    """Backup nagłówka jako SUROWY REGION bajtów pliku + metadane (od 2026-09-26, obie drogi zapisu).

    Tekst w `header_backups.header_text` (kolumna TEKSTOWA): `HORREUM-REGION/1 {json}`, nowa linia,
    base64 z `zlib` regionu. `offset`/`region` = gdzie i co leżało; `size`/`ino` = plik w chwili
    backupu; `pre_hash` = `header_hash` nagłówka w regionie.

    Region FITS = `[hdrLoc, datLoc)` wybranego HDU, XISF = `[0, first_attachment)`: sygnatura, pole
    długości, `reserved`, XML i CAŁE wypełnienie - więc undo w miejscu odtwarza bajt w bajt także
    niezerowe wypełnienie i zera po `END`. Backupy sprzed tej zmiany (gołe `hdr.tostring()` / XML)
    tego nie obiecują i cofają się wyłącznie drogą atomową. Materiałem ODZYSKU rozdartego zapisu
    nie jest ta koperta, tylko operacja `inplace_op` (0022) - koperta mówi, co było, operacja mówi,
    co się działo.

    `file_sha1` (opcjonalne, od 2026-09-27) = sha1 CAŁEGO pliku sprzed zapisu, gdy pisarz musiał go
    policzyć pełnym odczytem (baza nie miała kotwicy) - kontrola danych dokończenia bierze go stąd,
    gdy `location.file_sha1` jest pusty. Droga atomowa niesie go ZAWSZE (od 2026-10-05, AR-19): to
    dowód, że cofnięcie oddało plik bajt w bajt (`write_full_header`, `WriteResult.byte_exact`)."""
    fmt: str               # 'fits' | 'xisf'
    offset: int
    region: bytes
    size: int
    ino: int               # 0 = system nie podał
    pre_hash: str
    file_sha1: str | None = None

    def encode(self) -> str:
        meta = {"fmt": self.fmt, "offset": self.offset, "length": len(self.region),
                "size": self.size, "ino": self.ino, "pre_hash": self.pre_hash}
        if self.file_sha1 is not None:
            meta["file_sha1"] = self.file_sha1
        body = base64.b64encode(zlib.compress(self.region, 9)).decode("ascii")
        return f"{_BACKUP_MAGIC}{json.dumps(meta, sort_keys=True)}\n{body}"

    @staticmethod
    def decode(text: str) -> RegionBackup | None:
        """`None` dla backupu tekstowego sprzed 2026-09-26; uszkodzona koperta → `ValueError`."""
        if not text.startswith(_BACKUP_MAGIC):
            return None
        head, _, body = text[len(_BACKUP_MAGIC):].partition("\n")
        meta = json.loads(head)
        region = zlib.decompress(base64.b64decode(body))
        if len(region) != meta["length"]:
            raise ValueError("RegionBackup: długość regionu nie zgadza się z metadanymi")
        return RegionBackup(meta["fmt"], meta["offset"], region, meta["size"], meta["ino"],
                            meta["pre_hash"], meta.get("file_sha1"))

    def header_text(self) -> str:
        """Nagłówek jako tekst dla drogi atomowej undo: FITS - region, XISF - XML z regionu."""
        if self.fmt == "fits":
            return self.region.decode("latin-1")
        (hlen,) = struct.unpack("<I", self.region[8:12])
        return self.region[scan.XISF_XML_OFFSET:scan.XISF_XML_OFFSET + hlen].decode("utf-8")


def _backup_pre_hash(path: str, backup_text: str) -> str:
    """`header_hash` nagłówka zapisanego w backupie - tą samą formułą co skan."""
    env = RegionBackup.decode(backup_text)
    if env is not None:
        return env.pre_hash
    if _is_xisf(path):
        return hashlib.sha1(backup_text.encode("utf-8")).hexdigest()
    return scan._header_hash(fits.Header.fromstring(backup_text))


def _probe(fh, offset: int, length: int, size: int) -> tuple:
    """Odcisk próbek POZA regionem `[offset, offset+length)`: 64 KiB przed nim, 64 KiB od jego końca
    (początek danych) i 64 KiB końca pliku - sha1 hex każdej."""
    end = offset + length
    odcinki = ((max(0, offset - _PROBE_BYTES), offset),
               (end, min(size, end + _PROBE_BYTES)),
               (max(end, size - _PROBE_BYTES), size))
    wynik = []
    for a, b in odcinki:
        fh.seek(a)
        wynik.append(hashlib.sha1(fh.read(max(0, b - a))).hexdigest())
    return tuple(wynik)


_SHA1_BUF = 1 << 20


def _sha1_uchwytu(fh) -> str:
    """sha1 CAŁEGO pliku z uchwytu blokady (kotwica sprzed zapisu, gdy baza jej nie ma albo opisuje
    plik o innym `mtime`) - ten sam plik, który za chwilę zapiszemy, nikt inny go nie zmieni."""
    h = hashlib.sha1()
    fh.seek(0)
    while True:
        b = fh.read(_SHA1_BUF)
        if not b:
            break
        h.update(b)
    return h.hexdigest()


@dataclasses.dataclass(frozen=True)
class FileAnchor:
    """KOTWICA BAZY dla zapisu w miejscu: `location.file_sha1` i `location.mtime` sprzed zapisu.
    Pisarz sprawdza ją pod blokadą przed pierwszym bajtem (brak sha1 albo inny `mtime` → pełny
    odczyt; inny sha1 → 'blocked') i utrwala przy operacji (`OpSpec.anchor_sha1`, 0023), a kontrola
    danych dokończenia porównuje z nią plik po zapisie.

    `strict` = TRYB ŚCISŁY (astra, 2026-09-27): pełny odczyt uchwytu blokady ZAWSZE, niezależnie od
    `mtime` - reguła „ten sam `mtime` = ten sam plik" nie łapie pliku zmienionego poza nagłówkiem
    przy zachowanym `mtime`. Niezgodność → 'blocked' bez operacji w dzienniku, plik nietknięty.
    Kosztuje jeden pełny odczyt pliku więcej, więc włącza go tryb pilotażu (`commit(fallback=False)`),
    a wsad zostaje przy regule `mtime` z drogą powrotu (`recover_torn` dla `written`)."""
    file_sha1: str | None
    mtime: str | None
    strict: bool = False


@dataclasses.dataclass(frozen=True)
class _KontrolaDanych:
    """Czego re-sync po zapisie w miejscu wymaga od pliku, zanim wciągnie go do bazy: nagłówek
    `header_hash` (ten, który operacja zapisała) i sha1 pliku z podstawionym starym regionem
    operacji (`old_region` od `offset`) == `anchor_sha1` (kotwica sprzed zapisu).

    Podstawiony sha1 to sha1 pliku SPRZED operacji, o ile operacja zmieniła wyłącznie swój region -
    równość z kotwicą dowodzi, że żaden bajt POZA regionem nagłówka się nie zmienił, także drugie
    HDU FITS i kolejne obrazy/załączniki XISF, których nie widzą ani próbki, ani `sha1_data`. Liczy
    go ten sam pełny odczyt, który re-sync i tak robi (`_skan_kontrolny` → `scan_file(substitute=)`,
    AR-24), pod blokadą pliku - więc hasze pliku, danych i podstawiony opisują te same bajty.

    `wlasne` (cofnięcie drogą atomową, AR-182) = pary `(sha1 pliku, header_hash)` wyników WŁASNYCH
    cofnięć z ich śladów (`atomic_undo`): plik, którego oba odciski są parą JEDNEGO śladu, jest wynikiem
    tego cofnięcia - także wtedy, gdy nie jest plikiem sprzed commitu (zmiana od commitu, droga
    semantyczna, backup tekstowy). Para, nie sam sha1: rekord złożony z dwóch wersji pliku nie
    przejdzie. Bez regionu (`old_region=None` - backup tekstowy) nie ma podstawienia ani kotwicy."""
    offset: int
    old_region: bytes | None
    anchor_sha1: str | None
    header_hash: str
    wlasne: frozenset = frozenset()

    def __post_init__(self):
        if self.anchor_sha1 is not None and self.old_region is None:
            raise ValueError("kotwica sha1 bez regionu do podstawienia - błąd wołającego")


@contextlib.contextmanager
def _exclusive(path: str):
    """Uchwyt `r+b` z BLOKADĄ ZAPISU INNYCH (krok 0 sekcji): `CreateFileW(GENERIC_READ |
    GENERIC_WRITE, FILE_SHARE_READ, OPEN_EXISTING)`. Zmierzone 2026-09-26: na NTFS (tmp) i na
    udziale SMB (`R:\\_test_blokady`, poza archiwum) przy trzymanym uchwycie zapis z INNEGO procesu,
    drugie otwarcie do zapisu, usunięcie i `os.replace` na ten plik → odmowa; odczyt osobnym
    uchwytem i zapis własnym działają; `st_ino` stabilny (niezerowy) między otwarciami i po zapisie.
    Niezmierzone: drugi komputer. Drogi atomowe (`write_changes`, `write_xisf_changes`,
    `write_full_header`) trzymają ją przez odczyt i przygotowanie pliku tymczasowego (AR-18).
    Błąd współdzielenia/blokady przy otwarciu → ponów z przerwami `_LOCK_RETRY_DELAYS`, potem
    `OSError` z kodem i ścieżką pliku (`_blad_windows`, AR-242; zapis się nie zaczął). Poza Windows →
    `OSError` (zapis w miejscu niedostępny).

    WŁASNOŚĆ DESKRYPTORA (astra Z14): deskryptor CRT należy do tej funkcji i jest zamykany dokładnie
    raz w zewnętrznym `finally`; obiekt pliku dostaje go z `closefd=False`, więc wyjątek przy jego
    budowie ani przy jego zamknięciu nie zostawia uchwytu (a z nim blokady) otwartego."""
    if sys.platform != "win32":
        raise OSError("zapis w miejscu wymaga blokady współdzielenia Windows (CreateFileW)")
    import msvcrt
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    k32.CloseHandle.argtypes = (wintypes.HANDLE,)
    invalid = wintypes.HANDLE(-1).value
    generic_rw, share_read, open_existing, normal = 0xC0000000, 0x1, 3, 0x80
    for pauza in (*_LOCK_RETRY_DELAYS, None):
        handle = k32.CreateFileW(path, generic_rw, share_read, None, open_existing, normal, None)
        if handle not in (None, invalid):
            break
        err = ctypes.get_last_error()
        if err not in _LOCK_TRANSIENT or pauza is None:
            raise _blad_windows(err, path)
        time.sleep(pauza)
    try:
        fd = msvcrt.open_osfhandle(handle, os.O_RDWR | os.O_BINARY)
    except Exception:
        k32.CloseHandle(handle)
        raise
    try:
        fh = os.fdopen(fd, "r+b", closefd=False)
        try:
            yield fh
        finally:
            fh.close()
    finally:
        os.close(fd)


@dataclasses.dataclass(frozen=True)
class _InplacePlan:
    """Wszystko, co zapis w miejscu wie przed dotknięciem pliku. `old_region`/`new_region` mają
    TĘ SAMĄ długość i zaczynają się w `region_start`; `old_region` przeczytany Z UCHWYTU BLOKADY
    i sprawdzony; `pre_hash`/`post_hash` = header_hash przed/po formułą skanu."""
    fmt: str
    path: str
    region_start: int
    old_region: bytes
    new_region: bytes
    pre_hash: str
    post_hash: str


def _fits_layout(hdr) -> list:
    return [(c.keyword, c.value) for c in hdr.cards
            if c.keyword in _FITS_LAYOUT_KEYWORDS or re.fullmatch(r"NAXIS\d+", c.keyword)]


def _fits_region_checked(fh, start: int, data_start: int, expected_hash: str | None, uklad):
    """Region nagłówka FITS `[start, data_start)` PRZECZYTANY Z UCHWYTU BLOKADY i sprawdzony sam
    w sobie (Z1): długość = wielokrotność 2880 kończąca się blokiem z kartą `END` (granice HDU
    z bajtów, nie z offsetów parsera), `header_hash` == oczekiwany, układ danych == `uklad`.
    Zwraca `(raw, hash)` albo `WriteResult('blocked')` przy innym hashu; niespójne granice/układ
    → `ValueError` ('failed', zero zapisu)."""
    fh.seek(start)
    raw = fh.read(data_start - start)
    if len(raw) != data_start - start or not raw or len(raw) % 2880:
        raise ValueError(f"FITS: region nagłówka {start}:{data_start} niekompletny ({len(raw)} B)")
    rekordy = [raw[i:i + _FITS_RECORD] for i in range(0, len(raw), _FITS_RECORD)]
    koniec = next((i for i, r in enumerate(rekordy) if r == _FITS_END_RECORD), None)
    if koniec is None or len(raw) != -(-(koniec + 1) * _FITS_RECORD // 2880) * 2880:
        raise ValueError("FITS: granice nagłówka z uchwytu nie zgadzają się z kartą END")
    hdr = fits.Header.fromstring(raw.decode("latin-1"))
    biezacy = scan._header_hash(hdr)
    if expected_hash is not None and biezacy != expected_hash:
        return WriteResult("blocked", _HEADER_HASH_MISMATCH, None)
    if _fits_layout(hdr) != uklad:
        raise ValueError("FITS: układ danych z uchwytu inny niż z parsera")
    return raw, biezacy


def _rodzaj(value) -> str:
    """Rodzaj wartości karty dla zapisu w miejscu (AR-261): `tekst`, `logika`, `liczba` (int i float
    to jeden rodzaj) albo `inny` (wartość nieokreślona, zespolona). `bool` PRZED `int` - podklasa."""
    if isinstance(value, bool):
        return "logika"
    if isinstance(value, (int, float)):
        return "liczba"
    return "tekst" if isinstance(value, str) else "inny"


def _obraz_karty(karta, keyword: str, value, comment: str) -> tuple[bytes | None, str | None]:
    """Obraz 80 bajtów karty astropy `karta` (`keyword = wartość / comment`) albo `(None, powód)` -
    JEDNA reguła mieszczenia się karty w rekordzie dla pisarza w miejscu (karta po przebiegu próbnym
    `_apply_op`) i podglądu drogi (`_fits_card_image`, świeża karta). Round-trip: karta odczytana
    z obrazu ma dać tę samą nazwę i komentarz, a tekst - tę samą wartość: astropy przy za długim
    komentarzu UCINA go po cichu (ostrzeżenie), a przy za długiej wartości tekstowej składa CONTINUE;
    oba przypadki łapie ta kontrola. Wartości liczby nie porównujemy: liczba nie składa CONTINUE,
    a obraz, którego astropy nie odtworzy co do bitu (float dłuższy niż pole), zapisuje tak samo
    droga atomowa."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        image = karta.image
        back = fits.Card.fromstring(image)
        zgodna = (len(image) == _FITS_RECORD and back.keyword == keyword
                  and (not isinstance(value, str) or back.value == value.rstrip())
                  and (back.comment or "") == (comment or ""))
    if not zgodna:
        return None, PowodPozycji(f"karta {keyword} z zastanym komentarzem nie mieści się w jednym "
                                  f"rekordzie 80 znaków", "fb_card_too_long", keyword=keyword)
    return image.encode("latin-1"), None


def _fits_card_image(keyword: str, value, comment: str) -> tuple[bytes | None, str | None]:
    """Obraz ŚWIEŻEJ karty `keyword = wartość / comment` w układzie astropy (pole wartości stałego
    formatu, §4.2) albo `(None, powód)` - reguła `_obraz_karty` dla podglądu drogi bez pliku
    (`inplace_route`). `value` w typie karty: tekst albo - od AR-261 - liczba i logika (`_coerce`).
    Pisarz w miejscu bierze obraz karty Z PLIKU po przebiegu próbnym (`_fits_inplace_plan`): przy
    zmianie samego komentarza astropy zachowuje zastany format wartości (tekst dopełniony
    w apostrofach, `1.0E+00`), którego świeża karta nie ma."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        karta = fits.Card(keyword, value, comment)
    return _obraz_karty(karta, keyword, value, comment)


def _fits_hdu_bounds(path: str, expected_hash: str | None):
    """Odczyt parserem (pod blokadą wołającego): `(hdr, start, data_start, hash)` albo
    `WriteResult('blocked')`/`Fallback`. Offsety są tu KANDYDATEM - rozstrzyga `_fits_region_checked`."""
    with fits.open(path, mode="readonly", memmap=False) as hdul:
        index, hdu = scan._select_hdu(hdul)
        hdr = hdu.header
        biezacy = scan._header_hash(hdr)
        if expected_hash is not None and biezacy != expected_hash:
            return WriteResult("blocked", _HEADER_HASH_MISMATCH, None)
        if isinstance(hdu, fits.CompImageHDU):
            return Fallback(PowodPozycji("skompresowany master - nagłówek kafelkowy układa astropy",
                                         "fb_compressed"))
        info = hdul.fileinfo(index)
        return hdr, info["hdrLoc"], info["datLoc"], biezacy


_FITS_WOLNY_REKORD = b" " * _FITS_RECORD


def _wolne_rekordy(n: int) -> PowodPozycji:
    """Fragment „N wolnych rekordów” w dopełniaczu z odmianą PL (1 / reszta) - kod `free_records`,
    okno odmienia go w języku UI z parametru `n` (wpis mnogi, wzór `repo._kopie`)."""
    if n == 1:
        return PowodPozycji(f"{n} wolnego rekordu", "free_records", n=n)
    return PowodPozycji(f"{n} wolnych rekordów", "free_records", n=n)


def _brak_miejsca(przyrost: int, wolne: int) -> PowodPozycji:
    """Powód `fb_no_room` - jedno zdanie dla pisarza (`_fits_zloz_region`) i prognozy drogi z lustra
    kart (`inplace_route`): dopisanie potrzebuje `przyrost` wolnych rekordów za `END`, a jest `wolne`."""
    potrzebne = _wolne_rekordy(przyrost)
    return PowodPozycji(
        f"brak miejsca w nagłówku FITS: dopisanie potrzebuje {potrzebne} za END w ostatnim "
        f"bloku 2880 B, a jest {wolne} - nagłówek urósłby o blok i przesunął dane",
        "fb_no_room", needed=potrzebne, free=wolne)


def _fits_zloz_region(raw: bytes, ops: list[WriteOp], obrazy: dict[str, bytes]):
    """Region nagłówka FITS po łacie, złożony z rekordów → `(nowy region, karty oczekiwane)` albo
    `Fallback`. `raw` = region sprawdzony (`_fits_region_checked`), `obrazy` = obraz 80 B każdej
    karty łaty (`set` i `add`).

    KOLEJNOŚĆ KART daje astropy: `_apply_op` - ta sama funkcja, która łata drogę atomową - na
    nagłówku z TYCH bajtów. Dopisaną kartę astropy stawia za ostatnią kartą zwykłą, przed końcowym
    blokiem COMMENT/HISTORY/pustych, i zużywa pustą kartę z końca (`Header.append`, `useblanks`;
    zmierzone 2026-10-15, astropy 8.0). BAJTY daje plik: karta zastana wraca swoimi rekordami bajt
    w bajt (z kontynuacjami CONTINUE - ta sama reguła co `Header.fromstring`), karta łaty dostaje
    swój obraz. Karty ponad zużyte puste przesuwają `END` w dół o tyle wolnych rekordów (80 spacji)
    za `END` w ostatnim bloku 2880 B; brak → `Fallback`. Długość regionu, liczba bloków i początek
    danych zostają.

    Karty oczekiwane = nagłówek wyroczni wyrenderowany i przeczytany z powrotem TĄ SAMĄ funkcją co
    skan - to, co droga atomowa zapisuje na poziomie NAGŁÓWKA. Jej PLIK różni się jeszcze kartami
    skali: `writeto` przy danych pseudo-unsigned (`BZERO` bez `BSCALE`, NINA) dopisuje `BSCALE`
    i przenosi `BZERO` na koniec, a zapis w miejscu kart układu nie rusza."""
    rekordy = [raw[i:i + _FITS_RECORD] for i in range(0, len(raw), _FITS_RECORD)]
    koniec = rekordy.index(_FITS_END_RECORD)
    poczatki = [i for i in range(koniec) if i == 0 or rekordy[i][:8] != b"CONTINUE"]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        wyrocznia = fits.Header.fromstring(raw.decode("latin-1"))
        if len(poczatki) != len(wyrocznia.cards):
            raise ValueError("FITS: rekordy nagłówka nie składają się w karty tak jak u astropy")
        zrodlo = {id(c): b"".join(rekordy[a:b])
                  for c, a, b in zip(wyrocznia.cards, poczatki, poczatki[1:] + [koniec])}
        for op in ops:
            _apply_op(wyrocznia, op)
        nowe = []
        for c in wyrocznia.cards:
            if c.keyword in obrazy:
                # Droga atomowa zapisuje `Card.image` wyroczni (`writeto`), a obraz planu to ta sama
                # karta z przebiegu próbnego (`_fits_inplace_plan`, AR-261): przełożona - z zastanym
                # formatem wartości przy zmianie samego komentarza; nieprzełożona (wartość równa
                # zastanej wg reguły astropy, np. `-0.0` na `0.0`) - bajty pliku. Rozjazd znaczy, że
                # plan nie jest drogą atomową (EXPECT).
                if c.image.encode("latin-1") != obrazy[c.keyword]:
                    raise ValueError(f"FITS: obraz karty {c.keyword!r} w miejscu inny niż karta "
                                     f"drogi atomowej")
                nowe.append(obrazy[c.keyword])
            elif id(c) in zrodlo:
                nowe.append(zrodlo[id(c)])
            else:
                raise ValueError(f"FITS: astropy założył kartę {c.keyword!r} spoza łaty")
        want = scan._parse_cards(fits.Header.fromstring(wyrocznia.tostring()))
    przyrost = sum(len(r) for r in nowe) // _FITS_RECORD - koniec
    if przyrost < 0:
        raise ValueError(f"FITS: łata w miejscu ubyła {-przyrost} rekordów nagłówka")
    wolne = 0
    while koniec + 1 + wolne < len(rekordy) and rekordy[koniec + 1 + wolne] == _FITS_WOLNY_REKORD:
        wolne += 1
    if wolne < przyrost:
        return Fallback(_brak_miejsca(przyrost, wolne))
    nowy = b"".join(nowe) + _FITS_END_RECORD + raw[(koniec + 1 + przyrost) * _FITS_RECORD:]
    return nowy, want


def _fits_inplace_plan(path: str, fh, ops: list[WriteOp], expected_hash: str | None):
    """Plan zapisu w miejscu dla FITS (pod blokadą) → `_InplacePlan` | `Fallback` | `WriteResult`.

    Kwalifikują się operacje na WARTOŚCI zwykłej karty (nie komentarzowej, nie układu danych):
    `set` karty występującej dokładnie raz, z wartością tego samego rodzaju co zastana (tekst,
    logika, liczba - AR-261), i `add` karty, której w nagłówku nie ma (AR-118). Odmowy łaty
    (karta już jest, typ, wystąpienie, brak `idx`) daje przebieg próbny `_apply_op` przed
    kwalifikacją - te same co droga atomowa, bez spadku (AR-257). Obraz karty to karta Z TEGO
    przebiegu (`_obraz_karty`) - rekord, który zapisze droga atomowa, z komentarzem z operacji,
    a przy `set` bez komentarza - ZASTANYM (tu komentarz nie ginie), i z zastanym formatem wartości
    przy zmianie samego komentarza; karta, która się nie mieści
    w jednym rekordzie, spada na drogę atomową, a tam odmawia `_fits_comment_loss` (AR-7). Region
    składa `_fits_zloz_region`: `set` w TYM SAMYM slocie, `add` tam, gdzie postawiłby ją astropy,
    w zapasie nagłówka (pusta karta na końcu albo wolny rekord za `END`) - liczba bloków 2880 B
    i długość nagłówka zostają, brak zapasu → `Fallback`. Kontrola hasha i reguły karty stoją
    PRZED kwalifikacją, więc odmawiają tak samo jak droga atomowa; `CHECKSUM`/`DATASUM` → odmowa."""
    granice = _fits_hdu_bounds(path, expected_hash)
    if not isinstance(granice, tuple):
        return granice
    hdr, start, data_start, biezacy = granice
    powod = _ops_violation(ops, lambda op: op.op == "add" or _count_keyword(hdr, op.keyword) == 0)
    if powod is not None:
        return WriteResult("blocked", powod, None)
    powod = _odmowa_sumy(hdr)
    if powod is not None:
        return WriteResult("blocked", powod, None)
    # PRZEBIEG PRÓBNY ŁATY (AR-257): `_apply_op` - ta sama funkcja i kolejność co droga atomowa - na
    # JEDNEJ kopii nagłówka, po kolei (operacja widzi skutek poprzednich). Odmowa łaty (karta już jest,
    # typ, wystąpienie, brak `idx` - AR-256) zapada więc TU tym samym powodem, zamiast spadku, po
    # którym droga atomowa i tak by odmówiła; oryginał `hdr` nietknięty. Inny wyjątek (np. `nan`
    # z astropy) leci dalej jak w drodze atomowej - 'failed' bez zapisu (`_pod_blokada`).
    try:
        proba = hdr.copy()
        for op in ops:
            _apply_op(proba, op)
    except OdmowaZPowodem as exc:
        return WriteResult("blocked", exc.powod, None)
    obrazy: dict[str, bytes] = {}
    podmieniane: list[str] = []
    for op in ops:
        kw = op.keyword.strip().upper()
        if op.op not in ("set", "add"):
            return Fallback(PowodPozycji(
                f"operacja {op.op}/{op.value_type} na {kw} - układ karty zostaje przy astropy",
                "fb_op_kind", op=op.op, value_type=op.value_type, keyword=kw))
        if kw in _FITS_NOT_INPLACE or kw in _FITS_LAYOUT_KEYWORDS or kw in obrazy:
            return Fallback(PowodPozycji(f"karta {kw} nie jest zwykłą kartą tekstową",
                                         "fb_not_text_card", keyword=kw))
        wartosc = _coerce(op.value, op.value_type)          # po przebiegu próbnym - bez odmowy
        ile = _count_keyword(hdr, kw)
        if op.op == "add":
            komentarz = op.comment or ""
        else:
            if ile != 1 or op.idx not in (None, 0):
                return Fallback(PowodPozycji(f"karta {kw} występuje {ile} razy", "fb_card_count",
                                             keyword=kw, n=ile))
            card = hdr.cards[kw]
            # Karta liczbowa i logiczna W MIEJSCU (AR-261) wyłącznie przy ZGODNYM rodzaju wartości
            # zastanej i zapisu - zmiana rodzaju karty zostaje przy astropy (droga atomowa).
            if _rodzaj(card.value) != _rodzaj(wartosc):
                if isinstance(wartosc, str):
                    return Fallback(PowodPozycji(f"zastana wartość {kw} nie jest tekstem",
                                                 "fb_value_not_text", keyword=kw))
                return Fallback(PowodPozycji(
                    f"operacja {op.op}/{op.value_type} na {kw} - układ karty zostaje przy astropy",
                    "fb_op_kind", op=op.op, value_type=op.value_type, keyword=kw))
            komentarz = op.comment if op.comment is not None else card.comment
            podmieniane.append(kw)
        # Obraz = karta Z PRZEBIEGU PRÓBNEGO (kopia nagłówka po `_apply_op`) - to, co zapisze droga
        # atomowa (`writeto` bierze `Card.image`), także zastany format wartości przy zmianie samego
        # komentarza; nie świeża `fits.Card` (inny obraz tekstu dopełnionego, `1.0E+00`, `600.`).
        image, powod = _obraz_karty(proba.cards[kw], kw, wartosc, komentarz)
        if image is None:
            return Fallback(powod)
        obrazy[kw] = image
    uklad = _fits_layout(hdr)
    sprawdzony = _fits_region_checked(fh, start, data_start, biezacy, uklad)
    if isinstance(sprawdzony, WriteResult):
        return sprawdzony
    raw, _ = sprawdzony
    records = [raw[i:i + _FITS_RECORD] for i in range(0, len(raw), _FITS_RECORD)]
    for kw in podmieniane:
        nazwa = kw.ljust(8).encode("ascii")
        trafienia = [i for i, r in enumerate(records) if r[:8] == nazwa and r[8:10] == b"= "]
        if len(trafienia) != 1:
            return Fallback(PowodPozycji(f"karta {kw} stoi w {len(trafienia)} rekordach wartości",
                                         "fb_card_records", keyword=kw, n=len(trafienia)))
        i = trafienia[0]
        if i + 1 < len(records) and records[i + 1][:8] == b"CONTINUE":
            return Fallback(PowodPozycji(f"karta {kw} ma kontynuację CONTINUE", "fb_continue",
                                         keyword=kw))
    zlozony = _fits_zloz_region(raw, ops, obrazy)
    if isinstance(zlozony, Fallback):
        return zlozony
    new_raw, want = zlozony
    # Weryfikacja łaty PRZED zapisem (bliźniak `_xisf_verify`): karty z nowego nagłówka, wyłuskane
    # TĄ SAMĄ funkcją co skan, == karty, które daje `_apply_op` drogi atomowej (kolejność
    # włącznie); układ danych bez zmian.
    new_hdr = fits.Header.fromstring(new_raw.decode("latin-1"))
    if scan._parse_cards(new_hdr) != want or _fits_layout(new_hdr) != uklad:
        raise ValueError("FITS: karty po łacie w miejscu rozjechały się z oczekiwanymi")
    return _InplacePlan("fits", path, start, raw, new_raw, biezacy, scan._header_hash(new_hdr))


def _xisf_region_from_handle(fh, meta, expected: bytes) -> None:
    """Region `[0, first_attachment)` Z UCHWYTU BLOKADY musi być bajt w bajt tym, co parser widział
    (a więc mieć oczekiwany hash XML-a i te same adresy bloków); inaczej `ValueError`, zero zapisu."""
    fh.seek(0)
    if fh.read(len(expected)) != expected:
        raise ValueError("XISF: region nagłówka z uchwytu inny niż odczytany parserem")
    if hashlib.sha1(expected[scan.XISF_XML_OFFSET:
                             scan.XISF_XML_OFFSET + len(meta.xml_bytes)]).hexdigest() \
            != meta.header_hash:
        raise ValueError("XISF: hash nagłówka z uchwytu inny niż z parsera")


def _xisf_inplace_plan(path: str, fh, ops: list[WriteOp], expected_hash: str | None):
    """Plan zapisu w miejscu dla XISF (pod blokadą) → `_InplacePlan` | `WriteResult('blocked')`.
    Wszystkie bramki i weryfikacja nowego XML-a to `_xisf_prepare` - ta sama droga co plik
    tymczasowy. Region sprzed łaty składa ta sama funkcja co region po łacie
    (`build_xisf_header_region` z bieżącym XML-em), a zgodność z uchwytem blokady sprawdza
    `_xisf_region_from_handle`."""
    try:
        meta, new_xml, _, region = _xisf_prepare(path, ops, expected_hash)
    except _XisfRefusal as ref:
        return WriteResult("blocked", ref.reason, None)
    old = scan.build_xisf_header_region(meta, meta.xml_bytes)
    _xisf_region_from_handle(fh, meta, old)
    return _InplacePlan("xisf", path, 0, old, region, meta.header_hash,
                        hashlib.sha1(new_xml).hexdigest())


def _diff_range(old: bytes, new: bytes) -> tuple[int, int] | None:
    """Najmniejszy spójny zakres `[a, b)`, poza którym `old` i `new` są identyczne; `None` przy
    braku różnic. Długości MUSZĄ być równe (EXPECT - zapis w miejscu nie przesuwa bajtów)."""
    if len(old) != len(new):
        raise ValueError(f"zapis w miejscu: regiony różnej długości ({len(old)} != {len(new)})")
    if old == new:
        return None
    a = 0
    while old[a:a + 4096] == new[a:a + 4096]:
        a += 4096
    while old[a] == new[a]:
        a += 1
    b = len(old)
    while b - 4096 > a and old[b - 4096:b] == new[b - 4096:b]:
        b -= 4096
    while old[b - 1] == new[b - 1]:
        b -= 1
    return a, b


@dataclasses.dataclass(frozen=True)
class OpSpec:
    """Operacja zapisu w miejscu tak, jak ją utrwala dziennik `inplace_op` (0022) PRZED pierwszym
    bajtem: region stary i planowany wynikowy (ta sama długość, od `region_offset`), zakres zapisu
    `[write_start, write_end)` względem regionu, plik w chwili zapisu (`file_size`, `file_ino`),
    hash nagłówka przed i po, oraz `anchor_sha1` (0023) - sha1 CAŁEGO pliku sprzed zapisu, ustalony
    pod blokadą przed pierwszym bajtem (kotwica kontroli danych; `None` = pisarz bez kotwicy bazy,
    np. odzysk albo test pisarza)."""
    fmt: str
    region_offset: int
    old_region: bytes
    new_region: bytes
    write_start: int
    write_end: int
    file_size: int
    file_ino: int
    pre_hash: str
    post_hash: str
    anchor_sha1: str | None = None


class _NullJournal:
    """Dziennik bez zapisu - odzysk (pisze pod operacją, która już jest w dzienniku) i wołania
    bezpośrednie w testach pisarza."""

    def begin(self, spec, backup_text):
        pass

    def phase(self, faza, reason=None):
        pass


def _faza(journal, faza, reason=None) -> str | None:
    """Przejście fazy w dzienniku → `None` albo powód porażki. Porażka znaczy, że operacja zostaje
    w fazie `writing` (otwarta, izolowana), więc wołający MUSI potraktować zapis jako NIEUKOŃCZONY
    ('failed'), a nie dopisać powód do sukcesu (astra, 2026-09-27): baza nie wie, że zapis się
    udał, i jedyną uczciwą drogą dalej jest odzysk.

    `reason` fazy trafia do `inplace_op.reason` (`repo.set_inplace_op_phase`) - JAWNA granica bez
    kodu (AR-148): kolumna niesie samą prozę, 0042 jej nie dotyka, a okno jej nie czyta. Proza
    z surowym tekstem błędu systemu za zdaniem (`_proza_z_diagnoza`, AR-168) - kolumna nie ma
    `reason_args`, więc bez tego diagnoza z bazy ginęłaby razem z kodem."""
    try:
        journal.phase(faza, _proza_z_diagnoza(reason))
    except Exception as exc:  # noqa: BLE001
        blad = _blad_systemu(exc)
        return PowodPozycji(f"faza '{faza}' NIE zapisana w dzienniku ({blad}) - lokacja zostaje "
                            f"izolowana", "phase_not_saved", phase=faza, detail=blad)
    return None


def _apply_inplace(plan: _InplacePlan, fh, journal,
                   anchor: FileAnchor | None = None) -> WriteResult:
    """Kroki 2-4 zapisu w miejscu na uchwycie blokady `fh`. `journal.begin(spec, backup_text)`
    utrwala operację (a przy commicie także backup) PRZED zapisem; jego porażka → 'failed', plik
    nietknięty. Po zapisie `journal.phase('written'|'unverified')`; nieutrwalone `written` → 'failed'
    (operacja nieukończona). Wynik `in_place=True` wyłącznie wtedy, gdy zapis mógł ruszyć bajty.

    `anchor` (commit, undo): kotwica bazy sprawdzana pod blokadą przed dziennikiem - brak sha1, inny
    `mtime` niż w bazie albo tryb ścisły (`FileAnchor.strict`) → pełny odczyt uchwytu; sha1 inny niż
    w bazie → 'blocked', plik nietknięty, dziennik nieotwarty. Kotwica (z bazy potwierdzona `mtime`
    albo z pełnego odczytu) idzie do operacji (`OpSpec.anchor_sha1`), a z pełnego odczytu przy
    pustej bazie także do koperty backupu (`RegionBackup.file_sha1`). `None` = bez kotwicy (odzysk,
    testy pisarza)."""
    ruszony = False
    backup_text = None
    try:
        st = os.fstat(fh.fileno())
        size = st.st_size
        fh.seek(plan.region_start)
        if fh.read(len(plan.old_region)) != plan.old_region:
            return WriteResult("blocked", PowodPozycji("nagłówek na dysku zmienił się między "
                                                       "odczytem a zapisem - plik nietknięty",
                                                       "header_moved_before_write"), None)
        kotwica = koperta_sha1 = None
        if anchor is not None:
            if (anchor.strict or anchor.file_sha1 is None
                    or scan._mtime_iso(st) != anchor.mtime):
                kotwica = _sha1_uchwytu(fh)
                if anchor.file_sha1 is not None and kotwica != anchor.file_sha1:
                    return WriteResult("blocked", PowodPozycji(
                        "plik zmienił się od ostatniego skanu (sha1 całego pliku inny niż w bazie) "
                        "- kontrola danych po zapisie nie miałaby kotwicy; najpierw skan, plik "
                        "nietknięty", "anchor_mismatch"), None, code=CODE_CHANGED_SINCE_SCAN)
                if anchor.file_sha1 is None:
                    koperta_sha1 = kotwica      # baza kotwicy nie miała - koperta ją niesie
            else:
                kotwica = anchor.file_sha1      # reguła `mtime`: baza opisuje ten plik
        probka = _probe(fh, plan.region_start, len(plan.old_region), size)
        zakres = _diff_range(plan.old_region, plan.new_region) or (0, 0)
        spec = OpSpec(plan.fmt, plan.region_start, plan.old_region, plan.new_region, zakres[0],
                      zakres[1], size, st.st_ino, plan.pre_hash, plan.post_hash, kotwica)
        backup_text = RegionBackup(plan.fmt, plan.region_start, plan.old_region, size, st.st_ino,
                                   plan.pre_hash, koperta_sha1).encode()
        try:
            journal.begin(spec, backup_text)
        except Exception as exc:  # noqa: BLE001 - bez dziennika i backupu nie piszemy
            blad = _blad_systemu(exc)
            return WriteResult("failed", PowodPozycji(
                f"backup/dziennik operacji NIE powstał, więc zapisu nie było - plik nietknięty: "
                f"{blad}", "journal_not_saved", detail=blad), None)
        ruszony = True
        if zakres != (0, 0):
            fh.seek(plan.region_start + zakres[0])
            fh.write(plan.new_region[zakres[0]:zakres[1]])
        fh.flush()
        os.fsync(fh.fileno())
    except Exception as exc:  # noqa: BLE001 - raport zamiast wyjątku w warstwie zapisu
        if not ruszony:
            return WriteResult("failed", _blad_systemu(exc), None)
        blad = _blad_systemu(exc)
        powod = PowodPozycji(f"zapis w miejscu przerwany - bajty nagłówka mogły się zmienić: "
                             f"{blad}", "inplace_cut", detail=blad)
        dopisek = _faza(journal, "unverified", powod)
        return WriteResult("failed", _dopisz(powod, dopisek), plan.post_hash, backup_text,
                           in_place=True)
    wynik = _verify_inplace(plan, size, probka, backup_text)
    dopisek = _faza(journal, "written" if wynik.status == "applied" else "unverified", wynik.reason)
    if dopisek and wynik.status == "applied":
        return WriteResult("failed", PowodPozycji(
            f"plik ZMIENIONY w miejscu i zweryfikowany, ale {dopisek} - operacja NIEUKOŃCZONA",
            "inplace_unfinished", inner=dopisek), plan.post_hash, backup_text, in_place=True)
    if dopisek:
        wynik = dataclasses.replace(wynik, reason=_dopisz(wynik.reason, dopisek))
    return wynik


def _verify_inplace(plan: _InplacePlan, size: int, probka, backup_text) -> WriteResult:
    """Krok 4: osobny uchwyt odczytu (blokada nadal trzymana przez wołającego) - rozmiar, bajty
    regionu, próbki poza regionem, hash nagłówka formułą skanu. To odczyt KLIENTA: może przyjść
    z pamięci podręcznej systemu, więc nie jest niezależnym potwierdzeniem bajtów na serwerze.
    Każde „nie" → 'failed' z backupem (plik ZMIENIONY)."""
    try:
        with open(plan.path, "rb") as fh:
            size_po = os.fstat(fh.fileno()).st_size
            fh.seek(plan.region_start)
            region_po = fh.read(len(plan.new_region))
            probka_po = _probe(fh, plan.region_start, len(plan.new_region), size_po)
        post = _post_hash(plan.path)
    except Exception as exc:  # noqa: BLE001
        blad = _blad_systemu(exc)
        return WriteResult("failed", PowodPozycji(
            f"plik ZMIENIONY w miejscu, ale odczyt kontrolny klienta padł - {blad}",
            "inplace_verify_failed", detail=blad), plan.post_hash, backup_text, in_place=True)
    rozjazdy = [cecha for cecha, zgodne in (
        (_CECHA_ROZMIAR_PLIKU, size_po == size), (_CECHA_BAJTY_NAGLOWKA, region_po == plan.new_region),
        (_CECHA_PROBKA, probka_po == probka), (_CECHA_HEADER_HASH, post == plan.post_hash))
        if not zgodne]
    if rozjazdy:
        return WriteResult("failed", PowodPozycji(
            f"plik ZMIENIONY w miejscu, ale odczyt kontrolny klienta nie zgadza się: "
            f"{', '.join(rozjazdy)}", "inplace_verify_mismatch", features=rozjazdy),
            plan.post_hash, backup_text, in_place=True)
    return WriteResult("applied", None, post, backup_text, in_place=True)


def inplace_route(filetype, keyword: str, value: str, value_type, comment, *,
                  op: str = "set", cards=None) -> PowodPozycji | None:
    """PRZEWIDYWANIE drogi zapisu jednej karty (tekst, liczba, logika - AR-261) z faktów bazy, bez
    otwierania pliku (podgląd planu): `None` = w miejscu, `PowodPozycji` = powód drogi dotychczasowej
    (kod czyta okno - `fb_no_room`, `route_depends`). Reguła mieszczenia się
    karty FITS jest TA SAMA, której używa pisarz (`_obraz_karty` - tu na świeżej karcie,
    `_fits_card_image`), więc podgląd i zapis nie mogą się rozjechać co do rekordu 80 znaków; resztę
    (liczba kart, rodzaj i format zastanej wartości, CONTINUE, sumy kontrolne) rozstrzyga pisarz na
    pliku. XISF → `None`: brak rezerwy odmawia tak samo w obu drogach.

    Wartość niezgodna z `value_type` (tekst, który nie jest liczbą typu) → `OdmowaZPowodem`
    (`macro_type_mismatch`) z `_coerce`, nie powód drogi - dotyczy wyłącznie wołającego API spoza
    produktu: wołający produktu podają tekst (`object_change_dialog`), a podgląd makra odsiewa typ
    wcześniej.

    `op="add"` (AR-118): FITS dopisuje kartę w miejscu wyłącznie w zapasie nagłówka (pusta karta na
    końcu albo wolny rekord za `END` w ostatnim bloku 2880 B). `cards` (AR-155) = lustro kart
    nagłówka TEJ kopii (`(keyword, value_raw, value_type, comment)` z tabeli `cards`), z którego
    zapas daje się policzyć (`_zapas_z_lustra`): wolny rekord za `END` → `None`, pełny ostatni blok
    bez pustych kart → powód pisarza `fb_no_room` (cały plik przepisany). Bez lustra, z lustrem,
    które nie dowodzi układu rekordów, albo z pełnym blokiem i pustą kartą (pisarz zużyje ją
    wyłącznie wtedy, gdy stoi NA KOŃCU, a kolejności kart lustro nie trzyma) - powód „zależy od
    pliku”, nie `None`, który obiecałby zapis w miejscu."""
    if filetype == "xisf":
        return None
    powod = _fits_card_image(keyword, _coerce(value, value_type), comment or "")[1]
    if powod is None and op == "add":
        zapas = _zapas_z_lustra(cards) if cards else None
        if zapas == "free":
            return None
        if zapas == "full":
            # To samo zdanie i te same fakty, które poda pisarz (`_fits_zloz_region`): karta łaty
            # ma jeden rekord (`_fits_card_image` wyżej), a za `END` nie ma żadnego.
            return _brak_miejsca(1, 0)
        return PowodPozycji(
            f"zależy od pliku: dopisanie karty {keyword} do FITS idzie w miejscu, gdy nagłówek ma "
            f"zapas (pusta karta na końcu albo wolny rekord za END w ostatnim bloku 2880 B), "
            f"inaczej przepisuje cały plik", "route_depends", keyword=keyword)
    return powod


# Karty komentarzowe w lustrze: tekst stoi od kolumny 9 rekordu (bez `= `).
_FITS_KOMENTARZOWE = frozenset({"", "COMMENT", "HISTORY"})
_FITS_HIERARCH = "HIERARCH "


def _rekord_lustra_pewny(keyword: str, value_raw, value_type, comment) -> bool:
    """Czy karta lustra stała w pliku w JEDNYM rekordzie 80 B. Lustro buduje się po `hdr.cards`
    (`scan._parse_cards`), a `Header.fromstring` dokleja każdy rekord CONTINUE do karty przed nim -
    kartę z kontynuacjami lustro widzi jako jedną. Dowodem jednego rekordu jest dolna granica
    długości: treść karty w zapisie NAJCIAŚNIEJSZYM (`KEYWORD= 'wartość'/komentarz`, apostrof
    podwojony, HIERARCH z prefiksem) mieści się w 80 znakach. Dłuższa musiała przyjść
    z kontynuacjami, a ich liczby lustro nie zna. Liczby, logiki i niezdefiniowane - zawsze jeden
    rekord (astropy przy nich ucina komentarz, CONTINUE nie składa)."""
    if keyword in _FITS_KOMENTARZOWE:
        return 8 + len(value_raw or "") <= _FITS_RECORD
    if value_type != "str":
        return True
    naglowek = 10 if len(keyword) <= 8 else len(_FITS_HIERARCH) + len(keyword) + 1
    tekst = 2 + len((value_raw or "").replace("'", "''"))
    uwaga = 1 + len(comment) if comment else 0
    return naglowek + tekst + uwaga <= _FITS_RECORD


def _zapas_z_lustra(cards) -> str | None:
    """Zapas nagłówka FITS na jedną kartę jednorekordową z lustra kart (AR-155): `"free"` = za
    `END` w ostatnim bloku 2880 B stoi wolny rekord (pisarz dopisze w miejscu bez względu na puste
    karty), `"full"` = blok pełny, a pustej karty, którą astropy mógłby zużyć, nie ma (pisarz
    spadnie na drogę atomową), `None` = lustro tego nie rozstrzyga: karta z kontynuacjami CONTINUE
    (`_rekord_lustra_pewny`) albo pełny blok z pustą kartą, o której lustro nie wie, czy stoi na
    końcu (`Header.append` zużywa wyłącznie puste karty KOŃCOWE - `_fits_zloz_region`).

    Rekordów przed `END` jest tyle, ile kart w lustrze, gdy każda stoi w jednym rekordzie; `END`
    zajmuje następny, a nagłówek kończy się na najbliższej granicy 2880 B (36 rekordów - granicę
    z bajtów sprawdza pisarz, `_fits_region_checked`). Reguła zakłada nagłówek o MINIMALNEJ liczbie
    bloków: plik z dodatkowymi blokami spacji za blokiem `END` lustro widzi tak samo, a pisarz
    odmawia go jako `failed` (granice z uchwytu nie zgadzają się z kartą `END`) - na `R:` 0 na 323
    zmierzonych, rejestr."""
    rekordy = 0
    puste = False
    for keyword, value_raw, value_type, comment in cards:
        if not _rekord_lustra_pewny(keyword, value_raw, value_type, comment):
            return None
        rekordy += 1
        puste = puste or keyword == ""
    na_blok = 2880 // _FITS_RECORD
    if (rekordy + 1) % na_blok:
        return "free"
    return None if puste else "full"


def comment_loss_route(filetype, keyword: str, value: str, comment) -> str | None:
    """PRZEWIDYWANIE odmowy AR-7 dla `set` karty BEZ komentarza z faktów bazy (podgląd planu,
    AR-47): powód, gdy zastany komentarz nie przeżyje układu astropy przy nowej wartości, inaczej
    `None`. Odmawiają wtedy OBIE drogi - w miejscu `_obraz_karty` daje spadek, a droga
    atomowa `_fits_comment_loss` - więc plan ma taką klatkę pominąć, a nie liczyć jako spadek.
    Ta sama karta astropy co pisarz; XISF i karta bez komentarza → `None`. Fakty powodu:
    `comment_loss_lengths`."""
    dlugosci = comment_loss_lengths(filetype, keyword, value, comment)
    return None if dlugosci is None else _powod_ucietego_komentarza(keyword, *dlugosci)


def comment_loss_lengths(filetype, keyword: str, value: str, comment) -> tuple[int, int] | None:
    """FAKTY przepowiedni AR-7 (`comment_loss_route`): `(długość zastanego komentarza, długość po
    układzie karty astropy)` albo `None`, gdy komentarz przeżyje. Dla powierzchni, które mówią
    własnym językiem (okno zmiany obiektu, AR-138) - zdanie składają z tych liczb same."""
    if filetype == "xisf" or not comment:
        return None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        zostal = fits.Card.fromstring(fits.Card(keyword, value, comment).image).comment or ""
    if zostal == comment:
        return None
    return len(comment), len(zostal)


def _pod_blokada(path: str, dzialanie) -> WriteResult | Fallback:
    """Wykonaj `dzialanie(fh)` pod `_exclusive` i oddaj jego wynik także wtedy, gdy ZAMKNIĘCIE
    uchwytu rzuci (astra Z15): wynik z backupem i flagą mutacji przeżywa, a błąd zamknięcia
    dopisuje się do powodu. Wyjątek przed wynikiem (blokada, plan) → 'failed' bez zapisu."""
    wynik = None
    try:
        with _exclusive(path) as fh:
            wynik = dzialanie(fh)
    except Exception as exc:  # noqa: BLE001
        if wynik is None:
            return WriteResult("failed", _blad_systemu(exc), None)
        if isinstance(wynik, WriteResult):
            blad = _blad_systemu(exc)
            dopisek = PowodPozycji(f"zamknięcie uchwytu padło - {blad}", "handle_close_failed",
                                   detail=blad)
            return dataclasses.replace(wynik, reason=_dopisz(wynik.reason, dopisek))
    return wynik


def write_changes_inplace(path, ops: list[WriteOp], expected_hash: str | None, *,
                          journal=None, anchor: FileAnchor | None = None) -> WriteResult | Fallback:
    """Zapis nagłówka W MIEJSCU (O5) - kontrakt `WriteResult` jak `write_changes`, plus `Fallback`,
    gdy plik się nie kwalifikuje. Cały przebieg od planu po weryfikację trzyma blokadę
    `_exclusive`. `journal` (obiekt z `begin(spec, backup_text)` i `phase(faza, reason)`) MUSI
    utrwalić backup i operację przed pierwszym bajtem - orkiestracja podaje dziennik `inplace_op`;
    `None` = bez dziennika (testy pisarza). `anchor` = kotwica bazy (`FileAnchor`, zob.
    `_apply_inplace`). RAW → odmowa (#2)."""
    if _is_raw(path):
        return WriteResult("blocked", _RAW_READ_ONLY, None)
    path = os.fspath(path)
    journal = journal or _NullJournal()

    def _dzialanie(fh):
        plan = (_xisf_inplace_plan(path, fh, ops, expected_hash) if _is_xisf(path)
                else _fits_inplace_plan(path, fh, ops, expected_hash))
        if not isinstance(plan, _InplacePlan):
            return plan
        return _apply_inplace(plan, fh, journal, anchor)
    return _pod_blokada(path, _dzialanie)


def restore_inplace(path, backup: RegionBackup, *, op_new_region: bytes, op_file_size: int,
                    op_file_ino: int, op_post_hash: str, journal=None,
                    anchor: FileAnchor | None = None) -> WriteResult | Fallback:
    """UNDO W MIEJSCU (astra Z12/Z13) commitu zapisanego w miejscu: pod blokadą plik musi być TYM
    SAMYM plikiem (`st_ino`, rozmiar z operacji commitu), a CAŁY region pod offsetem backupu -
    bajt w bajt regionem wynikowym tej operacji (`op_new_region`). Wtedy wraca region z koperty.
    Inny inode/rozmiar → `Fallback` (plik podmieniony od commitu - droga atomowa rozstrzyga po
    hashu); region = stan sprzed commitu → 'blocked' „już cofnięte" z kodem `CODE_REGION_SPRZED`
    (czy cofnięcie jest domknięte, rozstrzyga orkiestracja dowodem całego pliku i bazy, AR-169);
    inny region → 'blocked'. `anchor` = kotwica bazy jak w `write_changes_inplace`."""
    if _is_raw(path):
        return WriteResult("blocked", _RAW_READ_ONLY, None)
    path = os.fspath(path)
    journal = journal or _NullJournal()

    def _dzialanie(fh):
        st = os.fstat(fh.fileno())
        if st.st_size != op_file_size or (op_file_ino and st.st_ino and st.st_ino != op_file_ino):
            return Fallback(PowodPozycji("plik podmieniony od commitu (rozmiar/st_ino) - cofnięcie "
                                         "atomowe", "fb_replaced_since_commit"))
        fh.seek(backup.offset)
        biezacy = fh.read(len(backup.region))
        if biezacy == backup.region:
            return WriteResult("blocked", _JUZ_REGION, None, code=CODE_REGION_SPRZED)
        if biezacy != op_new_region:
            return WriteResult("blocked", _REGION_ZMIENIONY, None)
        plan = _InplacePlan(backup.fmt, path, backup.offset, biezacy, backup.region, op_post_hash,
                            backup.pre_hash)
        return _apply_inplace(plan, fh, journal, anchor)
    return _pod_blokada(path, _dzialanie)


_JUZ_REGION = PowodPozycji("już cofnięte - region nagłówka jest stanem sprzed commitu",
                           "undo_already_region")
_REGION_ZMIENIONY = PowodPozycji("plik zmienił się od commitu - region nagłówka nie jest tym, "
                                 "który commit zapisał", "undo_region_changed")
# „Już cofnięte” drogi atomowej (AR-182) - każde z dowodem tego, co mówi: cały plik sprzed commitu
# (kotwica koperty), wynik własnego cofnięcia (para odcisków ze śladu `atomic_undo`) albo - backup
# tekstowy bez śladu, a ze śladem po skanie, który przyjął cały plik (AR-229) - sam nagłówek i baza,
# bo backup sprzed odcisku pliku reszty nie zna.
_JUZ_ATOMOWO = PowodPozycji("już cofnięte - cały plik i baza opisują stan sprzed commitu",
                            "undo_already")
_JUZ_WLASNE = PowodPozycji("już cofnięte - plik jest wynikiem cofnięcia zapisanym przez Horreum, "
                           "a baza go opisuje", "undo_already_own")
_JUZ_TEKST = PowodPozycji("już cofnięte - nagłówek i baza opisują stan sprzed commitu; backup sprzed "
                          "odcisku pliku nie pozwala sprawdzić reszty pliku", "undo_already_text")


def _bez_dowodu(niezgodne) -> PowodPozycji:
    """AR-169, AR-182: region nagłówka jest już stanem sprzed commitu (w miejscu i atomowo), ale cały
    plik nie ma dowodu stanu sprzed commitu ani wyniku własnego cofnięcia (`niezgodne` - werdykt
    kontroli danych) - cofnięcie nie jest domknięte."""
    return PowodPozycji(f"region nagłówka jest już stanem sprzed commitu, ale całego pliku nie da "
                        f"się potwierdzić ({niezgodne}) - przeskanuj plik; zmianę poza nagłówkiem "
                        f"rozstrzyga człowiek", "undo_region_unproven", inner=niezgodne)


def _bez_dowodu_wlasnego(niezgodne) -> PowodPozycji:
    """AR-182: plik rozpoznany NAGŁÓWKIEM (backup tekstowy albo nagłówek wyniku własnego cofnięcia,
    gdy bajty regionu koperty są inne), ale nie jest wynikiem cofnięcia ze śladu - zmienił się po nim;
    cofnięcie nie jest domknięte. Recepta skanu jest prawdziwa dla backupu tekstowego (AR-229): po
    skanie, który przyjął ten plik, cofnięcie mówi „już cofnięte” z granicą sprawdzenia."""
    return PowodPozycji(f"plik ma nagłówek sprzed commitu, ale nie jest wynikiem cofnięcia zapisanym "
                        f"przez Horreum ({niezgodne}) - przeskanuj plik; zmianę poza nagłówkiem "
                        f"rozstrzyga człowiek", "undo_own_unproven", inner=niezgodne)


def _stan_posredni(biezacy: bytes, spec: OpSpec) -> bool:
    """Czy region jest STANEM POŚREDNIM operacji `spec`: poza zakresem zapisu = stary, w zakresie
    każdy bajt równy staremu ALBO nowemu. Tylko taki stan mógł zostawić przerwany zapis tej
    operacji (jeden `write` spójnego zakresu, odzysk pisze wyłącznie ten zakres)."""
    a, b = spec.write_start, spec.write_end
    stary, nowy = spec.old_region, spec.new_region
    if len(biezacy) != len(stary) or biezacy[:a] != stary[:a] or biezacy[b:] != stary[b:]:
        return False
    return all(x == s or x == n for x, s, n in zip(biezacy[a:b], stary[a:b], nowy[a:b]))


def recover_region(path, spec: OpSpec) -> WriteResult:
    """ODZYSK ROZDARTEGO NAGŁÓWKA (astra Z11): przywróć region stary OTWARTEJ operacji `spec` pod
    jej offset, BEZ parsowania bieżącego pliku. Dowodem rozdarcia jest wyłącznie to, że region pod
    blokadą jest stanem pośrednim TEJ operacji (`_stan_posredni`) w tym samym pliku (rozmiar,
    `st_ino`). Zgodność rozmiaru i próbek niczego tu nie dowodzi - poprawna późniejsza przebudowa
    w miejscu może mieć ten sam rozmiar, inode i próbki, a stary region nadpisałby jej piksele.

    Odmowy ('blocked'): inny rozmiar/inode - nierozstrzygalne, instrukcja ręczna; region nie jest
    stanem pośrednim - „to nie jest rozdarcie tej operacji" (czytelny: obca zmiana; nieczytelny:
    nierozstrzygalne, instrukcja ręczna). Zapis dotyka wyłącznie zakresu operacji, więc przerwany
    odzysk zostawia znów stan pośredni i da się go ponowić."""
    if _is_raw(path):
        return WriteResult("blocked", _RAW_READ_ONLY, None)
    path = os.fspath(path)
    return _pod_blokada(path, lambda fh: _odzysk_pod_blokada(fh, path, spec))


# Drogi wyjścia z izolacji mają w oknie GESTY (menu prawego kliku w Zbiorach), a w skrypcie
# WYWOŁANIA. Powód mówi w obu formach naraz (AR-30 (1)): „gest” (`wywołanie`) - jedno zdanie,
# dwóch czytelników, bez mapowania po stronie GUI. Nazwy gestów = katalog GUI `grid.inplace.*`;
# rdzeń nie importuje GUI, więc równość pilnuje test (`test_gui_izolacja_zapisu`).
_GEST_DOKONCZ = "Dokończ zapis"
_GEST_PRZYWROC = "Przywróć nagłówek sprzed zapisu"
_GEST_ZWOLNIJ = "Zwolnij plik do skanu…"


def _droga_dokoncz(op_id) -> PowodPozycji:
    """Droga dalej w powodzie: „Dokończ zapis” (`finish_inplace(N)`) - fragment z kodem
    (`way_finish`, AR-148): okno mówi nazwą gestu w języku UI."""
    return PowodPozycji(f"„{_GEST_DOKONCZ}” (`finish_inplace({op_id})`)", "way_finish", op_id=op_id)


def _droga_przywroc(op_id) -> PowodPozycji:
    """Droga dalej w powodzie: „Przywróć nagłówek sprzed zapisu” (`recover_torn(N)`) - fragment
    z kodem (`way_restore`)."""
    return PowodPozycji(f"„{_GEST_PRZYWROC}” (`recover_torn({op_id})`)", "way_restore",
                        op_id=op_id)


# Recepta ręczna (fragment z kodem `way_manual`): plik, którego odzysk nie rozstrzygnie.
_RECZNA = PowodPozycji(
    f"nierozstrzygalne - przywróć plik z pełnej kopii ręcznie, potem zwolnij izolację: w Zbiorach "
    f"zaznacz klatkę i z menu prawego kliku wybierz „{_GEST_ZWOLNIJ}” "
    f"(`writeback.release_isolation`)", "way_manual")
# Kody niosące drogę wyjścia z izolacji (AR-148): wynik, który JUŻ mówi, jak wyjść, nie dostaje
# drugiej recepty zwolnienia ręką (`_zapisz_lokacje`, `_niesie_droge`). Zbiór JAWNY = kody, których
# zdanie spełnia DOKŁADNIE predykat dawnego parsera prozy: niesie `recover_torn` albo całą receptę
# ręczną `_RECZNA`. NIE cała rodzina `way_*` (`way_finish`/`way_retry*` tego nie niosą, a `isolated_*`
# niosą spoza rodziny) i NIE `finish_failed_isolated_release` (sam wynik tej recepty - niesie
# `release_isolation(…)`, ale nie całe `_RECZNA`). Równość z katalogiem pilnuje test (`test_powody_pisarza`).
_KODY_DROGI = frozenset({"way_restore", "way_manual", "isolated_recover", "isolated_finish"})
_INNY_PLIK = PowodPozycji(f"inny plik niż w chwili zapisu (rozmiar/st_ino); {_RECZNA}",
                          "inplace_other_file", way=_RECZNA)


def _niesie_droge(powod) -> bool:
    """Czy powód (z parametrami i uwagami, rekurencyjnie) niesie drogę wyjścia z izolacji: odzysk
    (`recover_torn`) albo receptę ręczną - po KODZIE (`_KODY_DROGI`), nie po prozie (AR-148;
    dawniej `"recover_torn" in reason or _RECZNA in reason`).

    Granice wobec dawnego parsera: proza NIE jest przeszukiwana - ani goły tekst w parametrze
    (`detail` z tekstem wyjątku), ani powód odczytany z bazy jako proza (wiersz sprzed 0042,
    `reason_args` spoza kodeka). Równoważność z dawnym parserem w wyniku dokończenia
    (`_zapisz_lokacje`) trzyma też człon `status == "failed"` przed tym wywołaniem: wyjątek
    dokończenia wraca jako 'failed', więc jego tekst parsera nie dotyka."""
    if not isinstance(powod, PowodPozycji):
        return False
    if powod.code in _KODY_DROGI:
        return True
    for _, wartosc in powod.params:
        wartosci = wartosc if isinstance(wartosc, (list, tuple)) else (wartosc,)
        if any(_niesie_droge(w) for w in wartosci):
            return True
    return False


def _odzysk_pod_blokada(fh, path: str, spec: OpSpec) -> WriteResult:
    """Rdzeń `recover_region` na uchwycie blokady `fh` - wspólny dla pisarza i orkiestracji
    `recover_torn`, która pod TĄ SAMĄ blokadą sprawdza fazę operacji przed i utrwala ją po."""
    st = os.fstat(fh.fileno())
    if st.st_size != spec.file_size or (spec.file_ino and st.st_ino
                                        and st.st_ino != spec.file_ino):
        return WriteResult("blocked", _INNY_PLIK, None)
    fh.seek(spec.region_offset)
    biezacy = fh.read(len(spec.old_region))
    if not _stan_posredni(biezacy, spec):
        try:
            _post_hash(path)
            czytelny = True
        except Exception:  # noqa: BLE001
            czytelny = False
        if czytelny:
            return WriteResult("blocked", PowodPozycji(
                "to nie jest rozdarcie tej operacji - nagłówek jest czytelny, ale to nie jest żaden "
                "stan pośredni zapisu (obca zmiana); odzysk odmawia", "not_torn_readable"), None)
        return WriteResult("blocked", PowodPozycji(f"to nie jest rozdarcie tej operacji; {_RECZNA}",
                                                   "not_torn_manual", way=_RECZNA), None)
    plan = _InplacePlan(spec.fmt, path, spec.region_offset, biezacy, spec.old_region, "",
                        spec.pre_hash)
    return _apply_inplace(plan, fh, _NullJournal())


# ============================================================ odczyty stagingu (core — literały)


def pending_for_run(con, run_id):
    """Wpisy stagingu przebiegu (do commitu i do szuflady GUI). Kolejność `id` = kolejność stagingu.
    Powód wpisu czyta `_powod_wiersza` (trójka z kodem, 0042)."""
    return con.execute(
        "SELECT id, location_id, keyword, idx, op, old_value, new_value, new_type, new_comment, "
        "       expected_header_hash, status, reason, reason_code, reason_args, withheld_id "
        "FROM pending_changes WHERE run_id = ? ORDER BY id",
        (run_id,),
    ).fetchall()


def _powod_wiersza(r):
    """Powód wpisu stagingu karty z trójki bazy (AR-148): `PowodPozycji`, gdy wiersz niesie kod,
    proza wiersza sprzed 0042 albo `None`; odczyt totalny (`item_reasons.z_bazy`)."""
    return z_bazy(r["reason"], r["reason_code"], r["reason_args"])


def backups_for_commit(con, commit_id):
    """Backupy nagłówków commitu (do undo) - bez backupów, po których pisarz pliku NIE podmienił
    (`unreplaced_at`, 0024, AR-37): commit go nie ruszył, więc cofnięcie nie ma tam czego cofać."""
    return con.execute(
        "SELECT id, location_id, hdu_index, header_text, post_hash "
        "FROM header_backups WHERE commit_id = ? AND unreplaced_at IS NULL ORDER BY id",
        (commit_id,),
    ).fetchall()


def _location(con, location_id):
    """Wiersz location potrzebny do zapisu: path, volume, header_hash, hdu_index, compressed, present
    + `sha1_data` klatki (kotwica re-syncu po zapisie w miejscu - `_resync(expect_sha1_data=)`)
    + `file_sha1`/`mtime` (kotwica bazy kontroli danych - `FileAnchor`)."""
    return con.execute(
        "SELECT l.id, l.frame_id, l.volume, l.path, l.header_hash, l.hdu_index, l.compressed, "
        "       l.present, l.mtime, l.file_sha1, f.sha1_data "
        "FROM location l JOIN frame f ON f.id = l.frame_id WHERE l.id = ?",
        (location_id,),
    ).fetchone()


# ============================================================ ORKIESTRACJA (commit / undo)


@dataclasses.dataclass(frozen=True)
class FileResult:
    location_id: int
    path: str
    # 'applied' | 'withheld' | 'blocked' | 'failed' | 'skipped' | 'restored' | 'released' | 'reconciled'
    # 'withheld' (AR-82) = plik ZAPISANY, a zeznanie klatki nie przyjęło jego nagłówka (inna kopia
    # mówi głosem klatki) - `code` = `CODE_ZEZNANIE_WSTRZYMANE`, dokończenie w `repo`.
    status: str
    reason: str | None = None
    code: str | None = None      # `CODE_*` powodu (patrz `WriteResult.code`)


@dataclasses.dataclass(frozen=True)
class CommitResult:
    run_id: str
    # None gdy żaden plik nie został podmieniony (applied ani failed po podmianie) - także wtedy,
    # gdy wiersz commitu z backupem powstał, a podmianę odbiła straż albo przerwała awaria.
    commit_id: int | None
    applied: list[FileResult]
    blocked: list[FileResult]
    failed: list[FileResult]
    skipped: list[FileResult]
    cancelled: bool = False
    # Podzbiór `applied` zapisany W MIEJSCU (`commit(inplace=True)`); reszta `applied` poszła drogą
    # dotychczasową, a jej `FileResult.reason` mówi, czemu (`Fallback.reason`).
    in_place: list[FileResult] = dataclasses.field(default_factory=list)
    # Rename: wynik `reconcile_renames` na wejściu (przerwane próby wszystkich przebiegów, AR-29).
    reconciled: list[FileResult] = dataclasses.field(default_factory=list)
    # Pliki ZAPISANE z zeznaniem wstrzymanym (AR-82, status 'withheld') - osobny kubeł, nie podzbiór
    # `failed`: zapis się dokonał, a „Cofnij” go cofa (`commit_id` jest).
    withheld: list[FileResult] = dataclasses.field(default_factory=list)


@dataclasses.dataclass(frozen=True)
class UndoResult:
    commit_id: int
    restored: list[FileResult]
    blocked: list[FileResult]
    failed: list[FileResult]
    cancelled: bool = False
    reconciled: list[FileResult] = dataclasses.field(default_factory=list)   # jak w `CommitResult`
    # Podzbiór `restored` cofnięty SEMANTYCZNIE (AR-19): nagłówek wrócił, ale bajty pliku są inne niż
    # przed commitem - powód w `FileResult.reason` mówi, czym (bliźniak `CommitResult.in_place`).
    semantic: list[FileResult] = dataclasses.field(default_factory=list)
    # Podzbiór `restored`, którego nagłówek wrócił, a zeznanie klatki NIE (AR-82) - głosem klatki
    # mówi inna kopia; `FileResult.code` = `CODE_ZEZNANIE_WSTRZYMANE`.
    withheld: list[FileResult] = dataclasses.field(default_factory=list)
    # Podzbiór `blocked`, w którym stan sprzed commitu JUŻ leży na dysku i w bazie („już cofnięte”,
    # commit, który pliku nie podmienił - `_CofniecieLokacji.juz`): nie ma czego cofać (AR-160).
    already: list[FileResult] = dataclasses.field(default_factory=list)
    # Przy przerwaniu (`cancelled`) - ile nieprzetworzonych backupów nie ma trwałego dowodu
    # zakończenia (`_cofniecie_zakonczone`, AR-176), czyli wymaga sprawdzenia ponowieniem; `None` =
    # pętla nie przerwana albo wynik bez tej wiedzy (`undo_renames`). Zdanie okna mówi liczbę albo
    # „pozostałe nie wymagają cofnięcia”, nie obietnicę.
    remaining: int | None = None

    @property
    def complete(self) -> bool:
        """Czy cofnięcie jest DOMKNIĘTE: pętla przeszła wszystkie backupy (bez `cancelled`), żaden
        plik nie padł, a każda blokada to „już cofnięte” (`already`). Tylko wtedy powierzchnia
        chowa uchwyt cofnięcia (AR-160); blokada do ponowienia (nieudana rekoncyliacja backupu,
        izolacja cudzą operacją, plik zmieniony od commitu) i błąd - uchwyt zostaje, powód mówi
        zdanie. Wynik bez `already` (np. `undo_renames`, który już cofnięte pomija) liczy każdą
        blokadę jako niedomkniętą."""
        return (not self.cancelled and not self.failed
                and all(fr in self.already for fr in self.blocked))


def _group_by_location(rows) -> list[tuple[int, list]]:
    """Grupuj wpisy stagingu po location_id, zachowując kolejność pierwszego wystąpienia."""
    order: list[int] = []
    groups: dict[int, list] = {}
    for r in rows:
        lid = int(r["location_id"])
        if lid not in groups:
            groups[lid] = []
            order.append(lid)
        groups[lid].append(r)
    return [(lid, groups[lid]) for lid in order]


def _resync(con, path, volume, *, now, actor="user:local", expect_sha1_data=None, kontrola=None,
            w_transakcji=None, przed_wciagnieciem=None) -> "_Resync":
    """RE-SYNC bazy po mutacji pliku - REUŻYWA znanej-ścieżki skanu (SPOT, R#2). `scan_file`
    (read-only, świeże hasze/nagłówek/karty) → `ingest_record`: `refresh_location` odświeża fakty
    kopii + zeznanie + `cards` + `frame.camera_id/kind` z eventami (actor="user:local"). Wymaga
    BRAKU otwartej transakcji (refresh bierze BEGIN IMMEDIATE) - funkcje stagingu `repo` commitują
    same, więc jest czysto.

    `expect_sha1_data` (zapis w miejscu): tożsamość danych, którą plik MA mieć po zapisie. Re-sync
    i tak czyta cały plik, więc to pełny dowód nietkniętych danych za darmo. Rozjazd → zwraca powód
    i NIE wciąga rekordu: `ingest_record` uznałby go za podmianę treści i rozdwoił klatkę
    (nowy frame + osierocony stary z zeznaniem i obiektem).

    `kontrola` (zapis w miejscu, `_KontrolaDanych`, astra 2026-09-27): `sha1_data` obejmuje tylko
    wybrane HDU / pierwszy obraz, więc przed wciągnięciem rekordu dwa kolejne warunki - nagłówek
    na dysku to ten, który operacja zapisała (`header_hash`), i plik z PODSTAWIONYM starym regionem
    operacji ma sha1 kotwicy sprzed zapisu (żaden bajt poza regionem się nie zmienił). Brak kotwicy
    to też odmowa: bez niej kontrola nie istnieje. Ingest BEZ generacji (`inplace_gen=None`) - to
    re-sync operacji, która sama izoluje lokację, więc nie może odrzucić sam siebie.

    Z kontrolą plik jest czytany w całości RAZ (`_skan_kontrolny`): sha1 pliku, danych i pliku
    z podstawionym starym regionem liczy jeden przebieg (AR-24).

    `w_transakcji(zeznanie)`: zapis bazy, który ma wejść RAZEM z wciągnięciem rekordu -
    jedna transakcja `repo.atomic`, odczyt pliku przed nią (blokada zapisu bazy nie trwa przez
    pełny odczyt). Cofnięcie odtwarza tak nagrobek ręki (AR-38): baza opisuje plik sprzed commitu
    z nagrobkiem albo żadne z dwojga.

    `przed_wciagnieciem` (bez argumentów): zapis w TEJ SAMEJ transakcji, ale PRZED wjazdem rekordu -
    rekoncyliacja backupu niepotwierdzonego (AR-40) bierze tak stan na własność, zanim klingi skanu
    (`confirm_failed_commit_by_scan`) zobaczą plik; jego odmowa (CAS) cofa transakcję, w której
    jeszcze nic się nie stało.

    DOWÓD ZEZNANIA (AR-82): po wjeździe rekordu, w tej samej transakcji, `scan.zeznanie_kopii`
    (z dociągnięciem, Z7) mówi, czy zeznanie klatki JEST odczytanym nagłówkiem - nie czy kopia ma
    prawo je przepisać. `w_transakcji(zeznanie)` dostaje ten dowód: zapis karty przy `False` jest
    wstrzymany, nie 'applied'. Cofnięcie zamyka OTWARTE wstrzymanie cofanego commitu jako `undone`
    w `przed_wciagnieciem` (`repo.close_withheld_undone`) - rozliczenie wstrzymań przy wjeździe
    (`repo._settle_withheld_tx`) zobaczyłoby inny nagłówek i nazwało je zastąpionym - a wynik tego
    zamknięcia rozstrzyga, czy cofnięcie bez dowodu zeznania samo zakłada wstrzymanie (B2).

    Zwraca `_Resync`: `niezgodne` (kontrola danych - nic nie wciągnięto, `zeznanie` `None`) albo
    `zeznanie`."""
    rec = _skan_kontrolny(path, kontrola)
    niezgodne = _kontrola_danych(rec, expect_sha1_data, kontrola)
    if niezgodne is not None:
        return _Resync(niezgodne, None)
    with repo.atomic(con):
        if przed_wciagnieciem is not None:
            przed_wciagnieciem()
        scan.ingest_record(con, rec, volume=volume, now=now, summary=scan.ScanSummary(),
                           actor=actor)
        zeznanie = _dowod_zeznania(con, rec, volume, now=now, actor=actor)
        if w_transakcji is not None:
            w_transakcji(zeznanie)
    return _Resync(None, zeznanie)


@dataclasses.dataclass(frozen=True)
class _Resync:
    """Wynik `_resync`: `niezgodne` - powód odmowy kontroli danych (rekord NIE wciągnięty);
    `zeznanie` - dowód, że zeznanie klatki jest odczytanym nagłówkiem pliku (AR-82)."""
    niezgodne: str | None
    zeznanie: bool | None


def _dowod_zeznania(con, rec, volume, *, now, actor) -> bool:
    """`scan.zeznanie_kopii` z dociągnięciem dla świeżo wciągniętego rekordu znanej kopii -
    w transakcji re-syncu. Rekord nieczytelny nie niesie zeznania → `False`."""
    if rec.header is None:
        return False
    loc = repo.location_by_path(con, volume=volume, path=rec.path)
    kind, _zrodlo, _ident, camera_id = scan._derive_axes(con, rec, now=now, actor=actor)
    return scan.zeznanie_kopii(con, rec, location_id=loc["id"], frame_id=loc["frame_id"],
                               sha1_data=scan._record_identity(rec)[0], camera_id=camera_id,
                               kind=kind, now=now, actor=actor, dociagnij=True)


def _skan_kontrolny(path, kontrola):
    """`scan.scan_file` pod werdykt `_kontrola_danych` - jedyne miejsce, które wiąże kontrolę danych
    z podstawieniem: z `kontrola` ten sam pełny odczyt liczy też `file_sha1_substituted` (sha1 pliku
    ze starym regionem operacji w miejscu nowego), bez niej - zwykły skan bez trzeciego hasha. Każda
    droga pytająca o werdykt (re-sync, powrót z `written`) czyta przez nią plik raz. Kontrola bez
    regionu (backup tekstowy, AR-182) - zwykły skan: dowodem jest wtedy wyłącznie wynik własny."""
    if kontrola is None or kontrola.old_region is None:
        return scan.scan_file(path)
    return scan.scan_file(path, substitute=(kontrola.offset, kontrola.old_region))


def _kontrola_danych(rec, expect_sha1_data, kontrola) -> str | None:
    """Warunki, które plik po mutacji musi spełnić, zanim re-sync go wciągnie (zob. `_resync`):
    `None` = zgodny, tekst = powód niezgodności. Wspólne dla re-syncu i drogi powrotu z `written`
    (`_powrot_z_written`), która pyta o werdykt bez wciągania. `rec` z kontrolą pochodzi
    z `_skan_kontrolny(path, kontrola)` - rekord bez podstawionego sha1 to błąd wołającego
    (`ValueError`), nie werdykt o pliku.

    Kotwicą jest sha1 pliku SPRZED operacji, utrwalony przy operacji (`inplace_op.anchor_sha1`,
    0023). Równość sha1 pliku z kotwicą NIE jest skrótem (astra, 2026-09-27): dawniej kotwicą była
    mutowalna `location.file_sha1`, a „sha1 == kotwica" przepuszczał każdy plik, którego fakty ktoś
    zdążył wciągnąć - także plik z bajtem zmienionym poza nagłówkiem. Kotwica niezmienna od chwili
    utrwalenia pozwala liczyć kontrolę od nowa przy każdym ponowieniu - w tym samym pełnym odczycie,
    który zwykła ścieżka i tak robi (bez osobnego odczytu, AR-24).

    WYNIK WŁASNY (cofnięcie drogą atomową, AR-182): para `(file_sha1, header_hash)` rekordu równa
    parze jednego śladu cofnięcia (`kontrola.wlasne`) przechodzi bez kotwicy - to odcisk treści
    zapisanej przez Horreum. Tożsamość klatki (`sha1_data`) sprawdzana jest i tak, przed nią."""
    if expect_sha1_data is not None and rec.sha1_data != expect_sha1_data:
        return PowodPozycji(f"plik ZMIENIONY, ale sha1_data po zapisie ({rec.sha1_data}) różni się "
                            f"od tożsamości klatki - baza NIE zsynchronizowana",
                            "data_identity_changed", sha1=rec.sha1_data)
    if kontrola is None:
        return None
    if (rec.file_sha1, rec.header_hash) in kontrola.wlasne:
        return None
    if rec.header_hash != kontrola.header_hash:
        return PowodPozycji("plik ZMIENIONY, ale nagłówek na dysku nie jest tym, który operacja "
                            "zapisała (header_hash) - baza NIE zsynchronizowana",
                            "check_header_other")
    if kontrola.anchor_sha1 is None:
        return PowodPozycji("brak kotwicy sha1 pliku sprzed zapisu - kontrola bajtów poza "
                            "nagłówkiem niemożliwa, baza NIE zsynchronizowana", "check_no_anchor")
    if rec.file_sha1_substituted is None:
        raise ValueError("rekord bez sha1 z podstawionym starym regionem - kontrola danych wymaga "
                         "skanu przez _skan_kontrolny(path, kontrola)")
    if rec.file_sha1_substituted != kontrola.anchor_sha1:
        return PowodPozycji("plik ZMIENIONY, a bajty POZA regionem nagłówka różnią się od pliku "
                            "sprzed zapisu (sha1 pliku z podstawionym starym regionem != kotwica "
                            "operacji) - baza NIE zsynchronizowana", "check_outside_changed")
    return None


def _powod_izolacji(op) -> str:
    """Powód odmowy mutacji pliku lokacji z operacją izolującą - z drogą naprawy właściwą fazie
    (drogi jak `_droga_*`: „gest okna” (`wywołanie rdzenia`)). Kod drogi dla okna (AR-141)."""
    if op["phase"] in repo.INPLACE_OPEN_PHASES:
        return PowodPozycji(
            f"lokacja ma nieukończony zapis w miejscu (operacja {op['id']}, {op['kind']}, faza "
            f"{op['phase']}) - plik jest izolowany; najpierw odzysk: „{_GEST_PRZYWROC}” "
            f"(`recover_torn({op['id']})`)", "isolated_recover",
            op_id=op["id"], op_kind=op["kind"], phase=op["phase"])
    return PowodPozycji(
        f"lokacja ma nieukończony zapis w miejscu (operacja {op['id']}, {op['kind']}, faza "
        f"{op['phase']}) - plik jest izolowany; najpierw dokończenie: „{_GEST_DOKONCZ}” "
        f"(`finish_inplace({op['id']})`), a gdy kontrola danych nie przechodzi - powrót: "
        f"„{_GEST_PRZYWROC}” (`recover_torn({op['id']})`)", "isolated_finish",
        op_id=op["id"], op_kind=op["kind"], phase=op["phase"])


def _powod_konfliktu(op) -> str:
    """Powód odmowy podmiany drogą atomową (`repo.InplaceConflict`, straż podmiany)."""
    if op["phase"] in repo.INPLACE_ISOLATING_PHASES:
        return _powod_izolacji(op)
    return PowodPozycji(
        f"lokacja dostała zapis w miejscu (operacja {op['id']}, {op['kind']}, faza {op['phase']}) "
        f"po odczycie pliku do podmiany - plik tymczasowy powstał ze stanu sprzed niego; podmiany "
        f"nie było, plik nietknięty - ponów po odświeżeniu stagingu", "inplace_after_read",
        op_id=op["id"], op_kind=op["kind"], phase=op["phase"])


def _kotwica_operacji(con, op, loc) -> str | None:
    """Kotwica kontroli danych operacji = sha1 pliku SPRZED niej, utrwalony przy operacji
    (`inplace_op.anchor_sha1`, 0023) - niezmienny, więc nic, co później pisze fakty lokacji, go nie
    przestawi. `None` = brak kotwicy (kontrola odmawia).

    Operacja sprzed 0023 (kolumna pusta): sha1 z pełnego odczytu pisarza w kopercie backupu commitu
    (`RegionBackup.file_sha1`), a gdy go nie ma - `location.file_sha1`, ale WYŁĄCZNIE gdy baza wciąż
    opisuje plik sprzed operacji (`location.header_hash == pre_hash` operacji). Po udanym re-syncu
    baza opisuje plik PO zapisie i jej `file_sha1` nie jest już kotwicą - dawniej brano ją bez tego
    warunku, więc spóźniony zapis faktów przestawiał kotwicę pod kontrolą."""
    if op["anchor_sha1"] is not None:
        return op["anchor_sha1"]
    if op["kind"] == "commit" and op["commit_id"] is not None:
        row = con.execute(
            "SELECT header_text FROM header_backups WHERE commit_id = ? AND location_id = ? "
            "ORDER BY id DESC LIMIT 1", (op["commit_id"], op["location_id"])).fetchone()
        try:
            env = RegionBackup.decode(row["header_text"]) if row is not None else None
        except ValueError:
            env = None
        if env is not None and env.file_sha1 is not None:
            return env.file_sha1
    if loc["file_sha1"] is not None and loc["header_hash"] == op["pre_hash"]:
        return loc["file_sha1"]
    return None


def _dokoncz(con, op_id, *, now) -> WriteResult:
    """DOKOŃCZENIE operacji zapisu w miejscu w fazie `written` → `synced` (krok 5 sekcji „ZAPIS
    W MIEJSCU"): wszystko POD BLOKADĄ pliku - faza czytana od nowa (inny proces mógł ją zmienić),
    brak nowszej operacji lokacji, ten sam plik (rozmiar, `st_ino`), region na dysku == wynik
    operacji (późniejsza cudza zmiana nie zostanie wciągnięta jako „nasza"), potem re-sync z kontrolą
    danych (`_resync(kontrola=)`) i CAS fazy `written` → `synced`.

    Jedna droga dla commitu (tuż po zapisie), ponowienia re-syncu commitu (`finish_inplace`),
    cofnięcia i ponowionego cofnięcia (`undo`). 'failed' = warunki spełnione, ale re-sync, kontrola
    danych albo utrwalenie fazy padły - operacja zostaje `written` (izolowana); powód mówi, która
    droga dalej: czkawka odczytu → ponowienie `finish_inplace`, kontrola danych NIE przeszła →
    droga powrotu `recover_torn` (stary nagłówek w miejscu + pełny skan). 'blocked' = plik nie jest
    wynikiem tej operacji albo operacja nie czeka na dokończenie.

    ZAMKNIĘCIE JEDNĄ TRANSAKCJĄ (`repo.finish_inplace_op`, astra 2026-09-27): faza `synced`, wpisy
    stagingu związane z operacją → 'applied' i zgaszenie nagrobka ręki przy wpisanym `OBJECT` -
    razem albo wcale. Dawniej robił to commit po powrocie stąd, a crash w środku zostawiał wiersze
    'pending', których ponowienie nie znajdowało. Od AR-82 (B1) ta transakcja to transakcja
    RE-SYNCU (`_resync(w_transakcji=)`): wjazd rekordu, dowód zeznania i zamknięcie operacji wchodzą
    razem - porażka zamknięcia cofa też wjazd, a ponowienie liczy wszystko od nowa."""
    op = con.execute("SELECT * FROM inplace_op WHERE id = ?", (op_id,)).fetchone()
    if op is None:
        return WriteResult("failed", _brak_operacji(op_id), None)
    loc = _location(con, int(op["location_id"]))
    if loc is None:
        return WriteResult("failed", _BRAK_LOCATION, None)
    spec = _spec_z_operacji(op)
    kontrola = _KontrolaDanych(spec.region_offset, spec.old_region,
                               _kotwica_operacji(con, op, loc), spec.post_hash)

    def _dzialanie(fh):
        faza = repo.inplace_op_phase(con, op_id)
        if faza != "written":
            return WriteResult("blocked", PowodPozycji(
                f"operacja {op_id} jest w fazie {faza}, nie czeka na dokończenie",
                "finish_not_waiting", op_id=op_id, phase=faza), None)
        if repo.newer_inplace_op(con, location_id=loc["id"], op_id=op_id):
            return WriteResult("blocked", PowodPozycji(
                f"lokacja ma operację nowszą niż {op_id} - dokończenie odmawia", "finish_newer_op",
                op_id=op_id), None)
        st = os.fstat(fh.fileno())
        if st.st_size != spec.file_size or (spec.file_ino and st.st_ino
                                            and st.st_ino != spec.file_ino):
            return WriteResult("blocked", _INNY_PLIK, None)
        fh.seek(spec.region_offset)
        biezacy = fh.read(len(spec.new_region))
        if biezacy != spec.new_region:
            droga = (PowodPozycji(f"przerwany powrót tej operacji - ponów: "
                                  f"{_droga_przywroc(op_id)}", "way_resume_return",
                                  way=_droga_przywroc(op_id))
                     if _stan_posredni(biezacy, spec) else _RECZNA)
            return WriteResult("blocked", PowodPozycji(
                f"region nagłówka na dysku nie jest wynikiem operacji {op_id} - plik zmienił się "
                f"od zapisu; {droga}", "finish_region_changed", op_id=op_id, way=droga), None)
        ponow = PowodPozycji(f"ponów: {_droga_dokoncz(op_id)}", "way_retry",
                             way=_droga_dokoncz(op_id))
        cofany = op["commit_id"] if op["kind"] == "undo" else None
        zamkniete: list[bool] = []         # B2: TO cofnięcie zamknęło otwarte wstrzymanie commitu
        zamkniecie: list = []              # (id wstrzymania | None, powód) z transakcji re-syncu
        padlo_zamkniecie: list[Exception] = []

        def _przed():
            if cofany is not None:
                zamkniete.append(repo.close_withheld_undone(
                    con, commit_id=cofany, location_id=loc["id"], now=now))

        def _zamknij(zeznanie):
            # B1: dowód zeznania, faza, staging i wstrzymanie - JEDNA transakcja re-syncu; inne
            # połączenie nie przestawi zeznania między dowodem a rozliczeniem operacji.
            powod = None
            if not zeznanie and op["commit_id"] is not None:
                powod = repo.withheld_reason(con, location_id=loc["id"],
                                             commit_id=op["commit_id"], undo=cofany is not None)
            try:
                zamkniecie.append((repo.finish_inplace_op(
                    con, op_id=op_id, now=now, testimony_ok=zeznanie, withheld_reason=powod,
                    closed_commit_withheld=bool(zamkniete and zamkniete[0])), powod))
            except Exception as exc:
                padlo_zamkniecie.append(exc)
                raise
        try:
            wynik = _resync(con, loc["path"], loc["volume"], now=now,
                            expect_sha1_data=loc["sha1_data"], kontrola=kontrola,
                            przed_wciagnieciem=_przed, w_transakcji=_zamknij)
        except Exception as exc:  # noqa: BLE001 - wsad idzie dalej, operacja zostaje `written`
            blad = _blad_systemu(exc)
            if padlo_zamkniecie:
                return WriteResult("failed", PowodPozycji(
                    f"faza 'synced' NIE zapisana ({blad}), a z nią re-sync bazy - jedna transakcja "
                    f"cofnięta w całości; {ponow}", "synced_not_saved", detail=blad, way=ponow),
                    None)
            return WriteResult("failed", PowodPozycji(
                f"plik ZMIENIONY, ale re-sync padł - {blad}; {ponow}", "resync_failed_retry",
                detail=blad, way=ponow), None)
        if wynik.niezgodne is not None:
            return WriteResult("failed", PowodPozycji(
                f"{wynik.niezgodne}; kontrola danych NIE przeszła - droga powrotu: "
                f"{_droga_przywroc(op_id)} przywraca stary nagłówek w miejscu i zwalnia plik do "
                f"pełnego skanu", "check_failed_way_back", inner=wynik.niezgodne,
                way=_droga_przywroc(op_id)), None)
        wstrzymanie, powod = zamkniecie[0]
        if wstrzymanie is not None:            # AR-82: plik zgodny, zeznanie przy innej kopii
            return WriteResult("applied", powod, spec.post_hash, code=CODE_ZEZNANIE_WSTRZYMANE)
        # Z8: powód wpisów niesie prawdę o nagrobku, który został mimo karty `OBJECT` - trójka
        # z kodem (0042, AR-148), więc okno mówi ją w języku UI.
        uwaga = con.execute("SELECT reason, reason_code, reason_args FROM pending_changes "
                            "WHERE inplace_op_id = ? AND reason IS NOT NULL LIMIT 1",
                            (op_id,)).fetchone()
        return WriteResult("applied", None if uwaga is None else _powod_wiersza(uwaga),
                           spec.post_hash)
    return _pod_blokada(loc["path"], _dzialanie)


def finish_inplace(con, op_id, *, now) -> FileResult:
    """PONOWIENIE DOKOŃCZENIA operacji zapisu w miejscu w fazie `written` (zapis zweryfikowany, ale
    kontrola danych, re-sync albo utrwalenie fazy padły, albo proces przerwał się przed re-synciem -
    lokacja izolowana). `_dokoncz` pod blokadą: kontrola danych od nowa wobec kotwicy operacji,
    re-sync i JEDNA transakcja zamknięcia (faza `synced`, wpisy stagingu ZWIĄZANE z operacją →
    'applied', zgaszenie nagrobka ręki, gdy łata wpisała `OBJECT` - `repo.finish_inplace_op`).
    Zwraca `FileResult` ('applied' | 'withheld' | 'blocked' | 'failed'); 'withheld' (AR-82) - faza
    domknięta, plik zgodny, a zeznanie klatki nie przyjęło zapisu operacji `commit`."""
    op = con.execute("SELECT * FROM inplace_op WHERE id = ?", (op_id,)).fetchone()
    if op is None:
        return FileResult(0, "", "failed", _brak_operacji(op_id))
    loc = _location(con, int(op["location_id"]))
    if loc is None:
        return FileResult(int(op["location_id"]), "", "failed", _BRAK_LOCATION)
    res = _dokoncz(con, op_id, now=now)
    status = ("withheld" if res.code == CODE_ZEZNANIE_WSTRZYMANE and op["kind"] == "commit"
              else res.status)
    return FileResult(loc["id"], loc["path"], status, res.reason, code=res.code)


def _rekoncyliuj_backupy(con, zalegle, loc, *, now) -> str | None:
    """REKONCYLIACJA BACKUPÓW NIEPOTWIERDZONYCH lokacji z dyskiem (AR-40, 0030) - pod blokadą pliku,
    zanim commit albo cofnięcie tknie lokację. `zalegle` = `repo.pending_header_backups`. Zwraca
    `None` (wszystkie rozstrzygnięte) albo powód, dla którego lokacja zostaje zablokowana (plik
    nieczytelny, blokada niedostępna, re-sync z niezgodną tożsamością) - ponowienie jest bezpieczne,
    backup zostaje niepotwierdzony."""
    path = loc["path"]
    try:
        for b in zalegle:
            # Backup z zamiarem podmiany (0038, AR-64) - automat pełnego sha1, bez blokady pliku
            # (podmiana systemowa wymaga pliku bez otwartego uchwytu, a ścieżki bywa brak); bez
            # zamiaru (sprzed 0038) - reguła dawna, pod blokadą.
            zamiar = repo.replace_intent(con, b["id"])
            if zamiar is not None:
                powod = _rekoncyliuj_zamiar(con, b, zamiar, loc, now=now)
            else:
                with _exclusive(path):
                    powod = _rekoncyliuj_backup(con, b, loc, now=now)
            if powod is not None:
                return powod
    except Exception as exc:  # noqa: BLE001 - raport zamiast wyjątku w warstwie zapisu
        blad = _blad_systemu(exc)
        return PowodPozycji(
            f"backup commitu {zalegle[0]['commit_id']} czeka na potwierdzenie podmiany, a "
            f"rekoncyliacja z dyskiem padła ({blad}) - lokacja zablokowana do ponowienia",
            "backup_reconcile_failed", commit_id=zalegle[0]["commit_id"], detail=blad)
    return None


def _rekoncyliuj_backup(con, b, loc, *, now) -> str | None:
    """Jeden backup niepotwierdzony (pod blokadą wołającego): nagłówek na dysku rozstrzyga.
      * == `post_hash` backupu → podmiana zaszła: re-sync pliku z kontrolą tożsamości i w JEGO
        transakcji `repo.settle_pending_backup(replaced=True)` (wpisy stagingu 'applied', nagrobek);
      * == nagłówek sprzed commitu → podmiany nie było: `unreplaced_at` (cofnięcie pominie);
      * inny → plik zmienił się poza programem: NIEROZSTRZYGNIĘTE, też `unreplaced_at` - backup bez
        dowodu wykonania nie cofa (A3).
    Rozstrzygnięcie idzie PRZED wjazdem rekordu w transakcji re-syncu (`przed_wciagnieciem`, A4):
    CAS odmawia, zanim cokolwiek się stanie, więc `repo.BackupAlreadySettled` znaczy wyłącznie
    pracę innego procesu → `None`. Po odmowie backup jest sprawdzany jeszcze raz - nadal
    niepotwierdzony to błąd, nie sukces. Re-sync z niezgodną tożsamością → powód, backup zostaje
    niepotwierdzony.

    Wpisy próby rozlicza PO wjeździe `repo.settle_backup_attempt` (AR-82): 'applied' z nagrobkiem
    wyłącznie przy dowodzie zeznania, inaczej zapis wstrzymany.

    REGUŁA DAWNA - wyłącznie dla backupu BEZ zamiaru podmiany (sprzed 0038): backup z zamiarem
    rozstrzyga `_rekoncyliuj_zamiar` pełnym sha1 (Z12)."""
    path = loc["path"]
    pre = _backup_pre_hash(path, b["header_text"])
    dysk = _post_hash(path)
    try:
        if dysk == b["post_hash"]:
            return _potwierdz_z_dysku(con, b, loc, now=now)
        repo.settle_pending_backup(con, backup_id=b["id"],
                                   replaced=False if dysk == pre else None, now=now)
    except repo.BackupAlreadySettled:
        return _po_odmowie(con, b, loc)
    return None


def _po_odmowie(con, b, loc) -> str | None:
    """Po `repo.BackupAlreadySettled`: backup nadal niepotwierdzony to błąd, nie sukces."""
    if any(z["id"] == b["id"] for z in repo.pending_header_backups(con, loc["id"])):
        return PowodPozycji(f"backup commitu {b['commit_id']} nadal niepotwierdzony po odmowie "
                            f"rozstrzygnięcia - lokacja zablokowana do ponowienia",
                            "backup_still_pending", commit_id=b["commit_id"])
    return None


def _potwierdz_z_dysku(con, b, loc, *, now, intent_outcome=None) -> str | None:
    """Podmiana zaszła (na dysku zapisana wersja): re-sync pliku z kontrolą tożsamości, a w JEGO
    transakcji potwierdzenie backupu (przed wjazdem, A4; z zamknięciem zamiaru `intent_outcome`)
    i rozliczenie wpisów próby po wjeździe (dowód zeznania, AR-82)."""
    proba: list[int] = []

    def _potwierdz():
        proba.extend(repo.settle_pending_backup(con, backup_id=b["id"], replaced=True, now=now,
                                                intent_outcome=intent_outcome))

    def _rozlicz(zeznanie):
        repo.settle_backup_attempt(
            con, backup_id=b["id"], pending_ids=proba, testimony_ok=zeznanie, now=now,
            withheld_reason=None if zeznanie else repo.withheld_reason(
                con, location_id=loc["id"], commit_id=b["commit_id"]))
    wynik = _resync(con, loc["path"], loc["volume"], now=now, expect_sha1_data=loc["sha1_data"],
                    przed_wciagnieciem=_potwierdz, w_transakcji=_rozlicz)
    if wynik.niezgodne is not None:
        return PowodPozycji(f"backup commitu {b['commit_id']} czeka na potwierdzenie podmiany; na "
                            f"dysku leży wersja tego commitu, ale {wynik.niezgodne}",
                            "backup_confirm_blocked", commit_id=b["commit_id"],
                            inner=wynik.niezgodne)
    return None


def _rekoncyliuj_zamiar(con, b, zamiar, loc, *, now) -> str | None:
    """REKONCYLIACJA BACKUPU Z ZAMIAREM PODMIANY (AR-64, 0038) - automat wznawialny po śmierci procesu
    w każdym etapie, bez blokady pliku. Wersje rozpoznaje WYŁĄCZNIE pełnym sha1 i rozmiarem (Z1, Z12):
    A = plik sprzed zapisu (`RegionBackup.file_sha1`), N = przygotowana wersja (zamiar), B = wersja
    innego pisarza zastana pod kopią (utrwalona przed powrotem, Z11). Pliki: P (ścieżka), K (kopia
    wyparta), Z (kopia zwrotna), T (plik tymczasowy).

    Faza `prepared` (zamiar utrwalony, nic więcej nie wiadomo). KAŻDY powrót cudzej wersji - także
    wykryty w biegu zapisu (`_WypartaDoPowrotu`) - idzie tym automatem: sha1 B i faza `returning`
    utrwalone PRZED pierwszą mutacją (C3):
      * Z istnieje - stan, którego żadna droga z zamiarem nie zostawia bez fazy powrotu → `kept`
        ze wszystkimi plikami (nikt nie kasuje i nie wnioskuje, czym był B);
      * K = B (≠ A): P = N → `returning`, potem powrót (`_powrot_b`); P brak → `returning`, potem
        K pod ścieżkę; P inne (C, choćby z nagłówkiem N) → `kept`;
      * K = A: P = N → potwierdzenie pod blokadą, K precz dopiero PO nim (C5); P brak → K wraca
        (`not_replaced`); P inne → `kept` (A zostaje - jedyna kopia wersji sprzed zapisu);
      * K brak: P = N → potwierdzenie pod blokadą; P = A → T (rozpoznana N) precz,
        `not_replaced`; inaczej → `kept` z T - plik tymczasowy znika wyłącznie, gdy pod ścieżką
        stoi A albo N; przy ścieżce pustej albo obcej bywa jedyną pełną kopią danych (C2).
    Fazy `returning`/`returned` - `_dokoncz_powrot`. Werdykt i zamknięcie zamiaru idą jedną
    transakcją (`repo.settle_pending_backup(intent_outcome=)`), `kept` zostawia zdarzenie ze ścieżkami
    i pliki obok ścieżki w stanie (`replace_intent.kept_paths`, wiersz Porządków, C8). Po `returned`
    baza jest odświeżana z pliku (C7). Zwraca `None` (lokacja wolna do zapisu) albo powód blokady."""
    env = RegionBackup.decode(b["header_text"])
    if env is None or env.file_sha1 is None:
        raise ValueError(f"backup {b['id']} z zamiarem podmiany bez sha1 pliku sprzed zapisu")
    a = (env.file_sha1, env.size)
    n = (zamiar["prepared_sha1"], zamiar["prepared_size"])
    p, k, z, t = loc["path"], zamiar["displaced_path"], zamiar["return_path"], zamiar["prepared_path"]
    cid = b["commit_id"]

    def _werdykt(outcome, replaced, powod=None, kept=()):
        if outcome == "returned":
            # C7: pod ścieżką wróciła cudza wersja, a baza mogła w międzyczasie przyjąć naszą
            # (skan po śmierci procesu). Trwały znacznik „przeczytaj od nowa” PRZED werdyktem -
            # śmierć między nimi zostawia backup niepotwierdzony, ponowienie dojdzie tu znowu.
            repo.mark_location_rescan(con, location_id=loc["id"], now=now,
                                      reason=f"powrót cudzej wersji po commicie {cid}")
        repo.settle_pending_backup(con, backup_id=b["id"], replaced=replaced, now=now,
                                   intent_outcome=outcome, kept_paths=tuple(kept))
        if outcome == "returned":
            powod = _dopisz(powod, _odswiez_po_powrocie(con, loc, now=now))
        return powod

    def _zostaw(*sciezki):
        # Pod ścieżką wersja nie do dowiedzenia (ani A, ani N): backup bez dowodu wykonania (A3).
        # Lokację blokuje wyłącznie plik ZOSTAWIONY obok (kopia wyparta albo zwrotna) - sam plik pod
        # ścieżką to zmiana poza programem, którą odbije kotwica stagingu, jak przed zamiarem.
        zostaja = [s for s in sciezki if s != p and os.path.exists(s)]
        slad = ([p] if os.path.exists(p) else []) + zostaja
        powod = None if not zostaja else PowodPozycji(
            f"przerwany commit {cid}: stanu plików nie da się dowieść pełnym sha1 - zostają do "
            f"oka: {', '.join(zostaja)}; zmiana NIE potwierdzona, cofnięcie tego commitu nic nie "
            f"ruszy", "commit_cut_unproven", commit_id=cid, paths=zostaja)
        return _werdykt("kept", None, powod, slad)

    powrot = PowodPozycji(
        f"przerwany commit {cid}: inny program zmienił plik w oknie podmiany - jego wersja wróciła "
        f"pod ścieżkę, zmiana NIE zapisana, cofnięcie tego commitu nic nie ruszy; odśwież staging "
        f"i zatwierdź ponownie", "commit_cut_other_returned", commit_id=cid)
    try:
        if zamiar["phase"] in ("returning", "returned"):
            return _dokoncz_powrot(con, b, loc, p, k, z, n, now=now, werdykt=_werdykt,
                                   zostaw=_zostaw, powrot=powrot)
        if os.path.exists(z):                    # bez fazy powrotu nie wiadomo, czym był B
            return _zostaw(p, k, z, t)
        sk = _sha1_pliku(k)
        sp = _sha1_pliku(p)
        if sk is not None and sk != a:           # B pod kopią
            if sp is not None and sp != n:
                return _zostaw(p, k, t)
            repo.mark_intent_returning(con, backup_id=b["id"], displaced_sha1=sk[0],
                                       displaced_size=sk[1])
            if sp is None:                       # 1177 pierwotnej podmiany: B wraca na pustą P
                _kopia_na_miejsce(k, p)
                return _dokoncz_powrot(con, b, loc, p, k, z, n, now=now, werdykt=_werdykt,
                                       zostaw=_zostaw, powrot=powrot)
            return _powrot_b(con, b, loc, p, k, z, n, now=now, werdykt=_werdykt, zostaw=_zostaw,
                             powrot=powrot)
        if sk is not None:                       # A pod kopią
            if sp is None:
                _kopia_na_miejsce(k, p)
                return _werdykt("not_replaced", False)
            if sp != n:
                return _zostaw(p, k, t)
            return _potwierdz_pod_blokada(con, b, loc, n, now=now, kopia_a=k)
        if sp == n:
            return _potwierdz_pod_blokada(con, b, loc, n, now=now)
        if sp == a:
            if _sha1_pliku(t) == n:              # pod ścieżką A - T (nasza N) zbędny
                _usun_kopie(t)
            return _werdykt("not_replaced", False)
        return _zostaw(p, t)
    except repo.BackupAlreadySettled:
        return _po_odmowie(con, b, loc)


def _nie_usunieta(commit_id, sciezka) -> str:
    return PowodPozycji(f"przerwany commit {commit_id}: rozpoznanej kopii {sciezka} nie dało się "
                        f"usunąć - lokacja zablokowana, ponowienie zapisu albo cofnięcia dokończy "
                        f"rekoncyliację", "commit_cut_copy_left", commit_id=commit_id, path=sciezka)


def _powrot_b(con, b, loc, p, k, z, n, *, now, werdykt, zostaw, powrot) -> str | None:
    """POWRÓT wersji innego pisarza (faza `returning` już utrwalona razem z jej sha1): podmiana
    systemowa `P ← K`, nasza wersja pod kopię zwrotną Z. Powrót, który nie zaszedł (stan nietknięty
    albo 1177 cofnięty), zostawia fazę - ponowienie spróbuje znowu."""
    blad = _replace_z_ponowieniem(p, k, z)
    try:
        zaszedl = _czy_zaszla(p, k, z, blad)
    except _PodmianaRozdarta as exc:
        return PowodPozycji(f"przerwany commit {b['commit_id']}: powrót wersji innego pisarza "
                            f"przerwany - {exc.reason}", "commit_cut_return_cut",
                            commit_id=b["commit_id"], inner=exc.reason)
    if not zaszedl:
        blad_powrotu = _blad_systemu(blad, z_typem=False)
        return PowodPozycji(
            f"przerwany commit {b['commit_id']}: powrót wersji innego pisarza pod ścieżkę nie "
            f"zaszedł ({blad_powrotu}) - pod {p} nasza wersja, wersja innego pisarza pod {k}, obie "
            f"zostają; ponowienie zapisu albo cofnięcia tej lokacji dokończy powrót, a gdy plik "
            f"pozostaje zajęty - przenieś {k} na {p} ręcznie", "commit_cut_return_failed",
            commit_id=b["commit_id"], detail=blad_powrotu, path=p, copy=k)
    return _dokoncz_powrot(con, b, loc, p, k, z, n, now=now, werdykt=werdykt, zostaw=zostaw,
                           powrot=powrot)


def _dokoncz_powrot(con, b, loc, p, k, z, n, *, now, werdykt, zostaw, powrot) -> str | None:
    """Wznowienie powrotu z faz `returning`/`returned` (Z11) - stan z dysku, pełnym sha1:
      * `returning`, K = B, Z brak, P = N → powrót jeszcze nie zaszedł: wykonaj go;
      * `returning`, P brak, K = B (1177 pierwotnej podmiany albo powrotu, Z brak albo = N) → K pod
        pustą ścieżkę;
      * `returning` → `returned` WYŁĄCZNIE, gdy powrót się dokonał: P = B, K brak, Z = N albo brak
        (C4); każdy inny stan (np. P = C, K = B, Z = N) → `kept` ze WSZYSTKIMI istniejącymi plikami;
      * `returned`: K wróciła albo Z ≠ N → `kept` (wszystko zostaje); Z = N → precz (rozpoznana N),
        potem P = B → `returned`, P inne (trzeci pisarz po powrocie) → `kept`.
    """
    zamiar = repo.replace_intent(con, b["id"])
    bb = (zamiar["displaced_sha1"], zamiar["displaced_size"])
    if zamiar["phase"] == "returning":
        sp, sk, sz = _sha1_pliku(p), _sha1_pliku(k), _sha1_pliku(z)
        if sk == bb and sz is None and sp == n:
            return _powrot_b(con, b, loc, p, k, z, n, now=now, werdykt=werdykt, zostaw=zostaw,
                             powrot=powrot)
        if sp is None and sk == bb and sz in (None, n):
            _kopia_na_miejsce(k, p)
            sp, sk = bb, None
        if sk is not None or sp != bb or sz not in (None, n):
            return zostaw(p, k, z)
        repo.mark_intent_returned(con, backup_id=b["id"])
    sk, sz = _sha1_pliku(k), _sha1_pliku(z)
    if sk is not None or sz not in (None, n):
        return zostaw(p, k, z)
    if sz is not None and _usun_kopie(z) is not None:
        return _nie_usunieta(b["commit_id"], z)
    if _sha1_pliku(p) == bb:
        return werdykt("returned", False, powrot)
    return zostaw(p, k, z)


def _potwierdz_pod_blokada(con, b, loc, n, *, now, kopia_a=None) -> str | None:
    """P = N z odczytu bez blokady - pod blokadą pełny sha1 jeszcze raz (inny pisarz mógł zdążyć),
    potem potwierdzenie z re-synciem (`_potwierdz_z_dysku`, zamknięcie zamiaru `replaced`).
    `kopia_a` (K rozpoznana jako A) znika DOPIERO po potwierdzeniu (C5): odmowa zostawia ją jako
    jedyną kopię wersji sprzed zapisu, a ponowienie trafi w gałąź „K = A, P inne” (`kept`)."""
    with _exclusive(loc["path"]) as fh:
        if (_sha1_uchwytu(fh), os.fstat(fh.fileno()).st_size) != n:
            return PowodPozycji(f"backup commitu {b['commit_id']}: plik zmienił się w trakcie "
                                f"rekoncyliacji - lokacja zablokowana do ponowienia",
                                "backup_changed_during", commit_id=b["commit_id"])
        powod = _potwierdz_z_dysku(con, b, loc, now=now, intent_outcome="replaced")
    if powod is None and kopia_a is not None and _usun_kopie(kopia_a) is not None:
        return None                      # commit potwierdzony; nieusunięta kopia A to tylko resztka
    return powod


def _odswiez_po_powrocie(con, loc, *, now) -> str | None:
    """C7: po powrocie cudzej wersji baza czyta plik od nowa (wjazd rekordu semantyką skanu - bez
    kotwic zapisu, bo pod ścieżką stoi wersja innego pisarza). Porażka zostawia trwały znacznik
    odczytu (`repo.mark_location_rescan`, postawiony przed werdyktem) - skan dokończy."""
    try:
        scan.ingest_record(con, scan.scan_file(loc["path"]), volume=loc["volume"], now=now,
                           summary=scan.ScanSummary(), actor="user:local")
    except Exception as exc:  # noqa: BLE001 - znacznik odczytu zostaje
        blad = _blad_systemu(exc)
        return PowodPozycji(f"baza nie odczytała jeszcze wróconej wersji ({blad}) - najbliższy skan "
                            f"przeczyta plik od nowa", "returned_not_read", detail=blad)
    return None


def commit(con, run_id, *, now, clock=None,
           progress: Callable[[int, int, str, str], None] | None = None,
           should_cancel: Callable[[], bool] | None = None,
           inplace: bool = False, fallback: bool = True) -> CommitResult:
    """Zapisz `pending_changes` (status 'pending') przebiegu do plików. Grupuje po LOCATION, per plik:
    kontrola `header_hash` (kotwica `expected_header_hash` ze stagingu, R#7) → BACKUP w bazie →
    zapis pliku → RE-SYNC (`refresh_location` przez `ingest_record`) → status 'applied'. Utrwalanie
    per plik (funkcje `repo` commitują), więc anulowanie (`should_cancel` PRZED plikiem) zostawia
    zapisane 'applied', resztę 'pending'. `progress(done, total, path, status)` po KAŻDYM pliku.
    Callbacki Qt-wolne (GUI podaje je z wątku roboczego).

    Bramki defensywne (makro już odsiało przy stagingu, ale stan mógł się zmienić): brak location /
    `present=0` / `compressed` → skipped z powodem, wpisy 'skipped'. `clock` = źródło `applied_at`
    commitu (domyślnie `now`).

    BACKUP PRZED ZAPISEM W OBU DROGACH (Z3, 2026-09-26): pisarz woła `_persist` (wiersz `commits`
    przy pierwszym pliku + `header_backups` z `RegionBackup`) przed `os.replace` albo przed
    pierwszym bajtem zapisu w miejscu. Porażka backupu → 'failed', plik nietknięty. Dawna
    kolejność (backup PO podmianie, D-X-14) zostawiała plik zmieniony bez drogi powrotu. Backup
    drogi atomowej, po którym straż odbiła podmianę ('blocked' bez `backup_text`), dostaje znacznik
    `unreplaced_at` (0024, AR-37) - cofnięcie commitu mieszanego go pomija, zamiast meldować
    blokadę o pliku, którego commit nie ruszył. Wyjątek przy samej podmianie ('failed' bez
    `backup_text`) znacznika NIE dostaje: na zerwanym udziale rename mógł zajść, więc backup zostaje
    kandydatem cofnięcia (kotwica `post_hash` przywróci plik podmieniony albo odbije nietknięty).

    ZAPIS POTWIERDZONY TYLKO CZĘŚCIOWO (`WriteResult` 'failed' z `backup_text`: weryfikacja po
    podmianie albo po zapisie w miejscu padła, zapis przerwany) → status 'failed' z numerem commitu,
    BEZ re-syncu i bez gaszenia nagrobka: bajtów na dysku nie potwierdzono. Plik ZAPISANY W MIEJSCU
    może być rozdarty - drogą naprawy jest `recover_torn` (backup regionu), nie re-skan.

    RE-SYNC sprawdza, że `sha1_data` pliku jest tożsamością klatki (rozjazd → 'failed' bez
    wciągania, zamiast rozdwojenia klatki), a jego wyjątek (czkawka SMB przy pełnym odczycie) daje
    'failed' dla tego pliku - wsad idzie dalej.

    BRAMKA IZOLACJI (obie drogi, astra 2026-09-27): lokacja z nieukończoną operacją zapisu w miejscu
    (`repo.isolating_inplace_op`) → 'blocked' z drogą naprawy (odzysk albo dokończenie), zero zapisu.
    Droga atomowa powtarza ją POD STRAŻĄ PODMIANY (`repo.guard_file_replace`): `os.replace` idzie
    w transakcji `BEGIN IMMEDIATE`, która sprawdza brak operacji izolującej i operacji zaczętej po
    generacji zapamiętanej przed bramką - zapis w miejscu, który zdążył się zmieścić między bramką
    a podmianą, odbija podmianę ('blocked', plik nietknięty), zamiast zostać przez nią starty.

    `inplace=True` (O5): per plik najpierw ZAPIS W MIEJSCU pod blokadą (`write_changes_inplace`,
    z kotwicą bazy `FileAnchor`) z dziennikiem `inplace_op` (backup + operacja z kotwicą + wiązanie
    wpisów stagingu jedną transakcją przed pierwszym bajtem; faza `written` po weryfikacji), a potem
    DOKOŃCZENIE (`_dokoncz`, znów pod blokadą: kontrola danych całego pliku + re-sync, a na końcu
    JEDNA transakcja: `synced`, wpisy 'applied', nagrobek). Porażka dokończenia → 'failed', lokacja
    izolowana w fazie `written`, dalej `finish_inplace` (czkawka) albo `recover_torn` (kontrola
    danych nie przeszła - droga powrotu). Plik niekwalifikujący się (`Fallback`) idzie
    drogą atomową, a jego `FileResult.reason` mówi dlaczego - chyba że `fallback=False` (tryb
    pilotażu, warunek 6 astry): wtedy 'blocked' z powodem i ZERO zapisu. `CommitResult.in_place` =
    pliki zapisane w miejscu.

    TRYB PILOTAŻU (`fallback=False`) włącza też TRYB ŚCISŁY kotwicy (`FileAnchor.strict`, astra
    2026-09-27): pisarz czyta cały plik pod blokadą przed operacją niezależnie od `mtime`, więc plik
    zmieniony poza nagłówkiem przy zachowanym `mtime` to 'blocked' bez operacji, a nie zapis, którego
    kontrola danych nie przejdzie. Wsad (`fallback=True`) zostaje przy regule `mtime` - bez
    dodatkowego pełnego odczytu - z drogą powrotu dla tego samego przypadku.

    BACKUP NIEPOTWIERDZONY (AR-40, 0030): backup drogi atomowej wchodzi do bazy z `pending_since`
    i gaśnie w transakcji straży podmiany, zaraz po podmianie (`repo.confirm_backup_replaced`).
    Lokacja z backupem niepotwierdzonym (proces zginął między backupem a podmianą, podmiana rzuciła)
    przechodzi NAJPIERW rekoncyliację z dyskiem (`_rekoncyliuj_backupy`): nagłówek commitu na dysku →
    podmiana zaszła (re-sync, wpisy stagingu 'applied', nagrobek); nagłówek sprzed commitu →
    `unreplaced_at`; inny → nierozstrzygnięte, też `unreplaced_at` (backup bez dowodu wykonania nie
    cofa). Potwierdzone z dysku zostają wyłącznie wpisy stagingu tej próby (`pending_rows`). Dopiero
    wtedy zapis. Po niej - bramka śladów cofnięcia (AR-127, `_rekoncyliuj_slady`): plik zostawiony obok
    ścieżki przez przerwane cofnięcie tej lokacji → werdykt `kept`, wiersz Porządków i jednorazowa
    blokada (wpisy 'blocked', zapis po ponownym stagingu); plików nikt nie rusza.

    ZEZNANIE WSTRZYMANE (AR-82, 0037): sukces zapisu to DOWÓD, że zeznanie klatki jest odczytanym
    nagłówkiem pliku (`_resync` → `scan.zeznanie_kopii`), nie samo prawo kopii do przepisania go.
    Gdy głosem klatki mówi inna obecna kopia, plik zostaje zapisany, ale wynik to 'withheld'
    (`CommitResult.withheld`, `commit_id` do cofnięcia jest): wpisy 'failed' z wiązaniem
    wstrzymania, nagrobek ręki żyje. Wszystkie trzy drogi (atomowa, w miejscu, rekoncyliacja
    backupu) rozliczają się tym samym dowodem; dokończenie - w `repo` (przejęcie zeznania tej kopii
    gestem albo Dostawą, pełny odczyt przy kopii wiodącej)."""
    pending = [r for r in pending_for_run(con, run_id) if r["status"] == "pending"]
    groups = _group_by_location(pending)
    total = len(groups)

    applied: list[FileResult] = []
    blocked: list[FileResult] = []
    failed: list[FileResult] = []
    skipped: list[FileResult] = []
    in_place: list[FileResult] = []
    withheld: list[FileResult] = []
    kubly = {"applied": applied, "blocked": blocked, "failed": failed, "skipped": skipped,
             "withheld": withheld}
    stan = _StanCommitu(run_id, clock or (lambda: now))
    cancelled = False
    done = 0

    def _report(path, status):
        nonlocal done
        done += 1
        if progress is not None:
            progress(done, total, path, status)

    for location_id, rows in groups:
        if should_cancel is not None and should_cancel():
            cancelled = True
            break
        zapis = _zapisz_lokacje(con, stan, location_id, rows, now=now, inplace=inplace,
                                fallback=fallback)
        kubly[zapis.wynik.status].append(zapis.wynik)
        if zapis.w_miejscu:
            in_place.append(zapis.wynik)
        _report(zapis.wynik.path, zapis.wynik.status)

    # `commit_id` wyłącznie przy pliku podmienionym (kontrakt `CommitResult.commit_id`): commit bez
    # podmiany nie ma czego cofać, a jego wiersz z backupem zostaje w bazie (append-only).
    return CommitResult(run_id, stan.commit_id if stan.podmieniono else None, applied, blocked,
                        failed, skipped, cancelled, in_place, withheld=withheld)


@dataclasses.dataclass
class _StanCommitu:
    """Stan przebiegu zapisu kart dzielony przez jego pliki (`commit`, sterownik zmiany obiektu):
    wiersz `commits` powstaje przy PIERWSZYM pliku, który naprawdę ma być ruszony, i obejmuje
    kolejne. `podmieniono` - czy choć jeden plik został naprawdę ruszony (`backup_text` w wyniku
    pisarza): wiersz commitu powstaje z backupem PRZED podmianą, więc sam `commit_id` tego nie mówi -
    podmiana odbita strażą albo awaria po backupie zostawiają commit z backupem, który niczego nie
    zmienił. `clock` = źródło `applied_at` commitu."""
    run_id: str
    clock: Callable[[], str]
    commit_id: int | None = None
    podmieniono: bool = False


@dataclasses.dataclass(frozen=True)
class _ZapisLokacji:
    """Wynik zapisu kart JEDNEJ lokacji. `w_miejscu` - 'applied' zapisany w miejscu
    (`CommitResult.in_place`). `dotknieto` - bajty pliku MOGŁY się zmienić: zapis zaszedł (także
    częściowo albo bez re-syncu) albo podmiana rzuciła po backupie i jest niepotwierdzona. Fałsz =
    plik na pewno nietknięty (odmowa bramki albo pisarza przed pierwszym bajtem) - sterownik zmiany
    obiektu wolno wtedy cofnąć przeniesienie tej pary („razem albo wcale”)."""
    wynik: FileResult
    w_miejscu: bool = False
    dotknieto: bool = False


def _zapisz_lokacje(con, stan, location_id, rows, *, now, inplace, fallback) -> _ZapisLokacji:
    """CIAŁO `commit` DLA JEDNEJ LOKACJI - JEDEN pisarz karty dla `commit` i sterownika zmiany
    obiektu (`commit_object_change`, para przeniesienie → karta). `rows` = oczekujące wpisy stagingu
    tej lokacji, `stan` = stan przebiegu (`_StanCommitu`: commit i podmiana). Zachowanie, bramki
    i statusy wpisów - opis `commit`; wynik niesie dodatkowo, czy plik mógł zostać ruszony."""
    def _mark(rows, status, reason):
        for r in rows:
            repo.set_pending_status(con, pending_id=r["id"], status=status, reason=reason)

    loc = _location(con, location_id)
    if loc is None:
        _mark(rows, "failed", _BRAK_LOCATION)
        return _ZapisLokacji(FileResult(location_id, "", "failed", _BRAK_LOCATION))
    path = loc["path"]
    if not loc["present"]:
        reason = _KOPIA_ZNIKNELA
        _mark(rows, "skipped", reason)
        return _ZapisLokacji(FileResult(location_id, path, "skipped", reason))
    if loc["compressed"]:
        reason = PowodPozycji("skompresowany master - edycja poza krokiem 4", "compressed_master")
        _mark(rows, "skipped", reason)
        return _ZapisLokacji(FileResult(location_id, path, "skipped", reason))
    # BRAMKA BACKUPU NIEPOTWIERDZONEGO (AR-40): przerwany commit drogi atomowej tej lokacji
    # (dowolnego przebiegu) najpierw rozstrzyga dysk - inaczej ponowiony zapis tej samej zmiany
    # dałby backup nierozróżnialny od tamtego, a cofnięcie starego commitu cofnęłoby nowy.
    zalegle = repo.pending_header_backups(con, location_id)
    if zalegle:
        reason = _rekoncyliuj_backupy(con, zalegle, loc, now=now)
        if reason is not None:
            _mark(rows, "blocked", reason)
            return _ZapisLokacji(FileResult(location_id, path, "blocked", reason))
        loc = _location(con, location_id)
        teraz = {r["id"]: r for r in pending_for_run(con, stan.run_id)}
        wstrzymane = [teraz[r["id"]] for r in rows
                      if r["id"] in teraz and teraz[r["id"]]["withheld_id"] is not None]
        rows = [r for r in rows if r["id"] in teraz and teraz[r["id"]]["status"] == "pending"]
        if not rows and wstrzymane:     # dysk potwierdził zapis, zeznanie go nie przyjęło (AR-82)
            return _ZapisLokacji(FileResult(location_id, path, "withheld",
                                            _powod_wiersza(wstrzymane[0]),
                                            code=CODE_ZEZNANIE_WSTRZYMANE), dotknieto=True)
        if not rows:                    # przerwany commit TEGO przebiegu potwierdził dysk
            commity = ", ".join(str(z["commit_id"]) for z in zalegle)
            reason = PowodPozycji(f"zapis potwierdzony z dysku po przerwanym commicie {commity} - "
                                  f"nic do zapisania", "confirmed_from_disk", commits=commity)
            return _ZapisLokacji(FileResult(location_id, path, "applied", reason), dotknieto=True)
    # BRAMKA ŚLADÓW COFNIĘCIA (AR-127): pliki zostawione obok ścieżki przez przerwane cofnięcie tej
    # lokacji dostają werdykt `kept` i wiersz Porządków - raz, przed zapisem; plik nietknięty.
    reason = _rekoncyliuj_slady(con, loc, now=now)
    if reason is not None:
        _mark(rows, "blocked", reason)
        return _ZapisLokacji(FileResult(location_id, path, "blocked", reason))
    # Generacja dziennika PRZED bramką izolacji (niżej), dla straży podmiany drogi atomowej: straż
    # odbije operację zaczętą po tej chwili (plik tymczasowy powstanie ze stanu sprzed niej).
    gen = repo.inplace_generation(con)
    izolujaca = repo.isolating_inplace_op(con, location_id)
    if izolujaca is not None:           # obie drogi: plik po nieukończonym zapisie w miejscu
        reason = _powod_izolacji(izolujaca)
        _mark(rows, "blocked", reason)
        return _ZapisLokacji(FileResult(location_id, path, "blocked", reason))

    ops = [WriteOp(keyword=r["keyword"], op=r["op"], value=r["new_value"],
                   value_type=r["new_type"], idx=r["idx"], comment=r["new_comment"])
           for r in rows]
    expected = rows[0]["expected_header_hash"]  # kotwica stagingu (R#7)

    backup_pliku: list[int] = []      # id backupu drogi atomowej utrwalonego dla TEGO pliku

    def _persist(backup_text, post_hash, zamiar):
        # Backup PRZED podmianą (droga atomowa): commit powstaje przy pierwszym pliku, który
        # naprawdę ma być ruszony.
        if stan.commit_id is None:
            stan.commit_id = repo.insert_commit(con, run_id=stan.run_id, now=stan.clock(),
                                                summary=f"run {stan.run_id}")
        # NIEPOTWIERDZONY do podmiany (AR-40): potwierdza go `_potwierdz` w transakcji straży;
        # niesie wpisy stagingu tej próby - rekoncyliacja potwierdzi wyłącznie je (A5). Razem
        # z nim ZAMIAR PODMIANY (AR-64): nazwy kopii i pełny sha1 naszej wersji, jedną transakcją.
        backup_pliku.append(repo.insert_header_backup(
            con, commit_id=stan.commit_id, location_id=location_id, hdu_index=loc["hdu_index"],
            header_text=backup_text, post_hash=post_hash, pending_since=now,
            pending_rows=tuple(rows), intent=zamiar))

    def _potwierdz():
        repo.confirm_backup_replaced(con, backup_id=backup_pliku[0], now=now)

    class _Dziennik:
        """Dziennik commitu w miejscu: backup + commit + operacja + wiązanie wpisów stagingu
        jedną transakcją."""
        op_id = None

        def begin(self, spec, backup_text):
            stan.commit_id, self.op_id = repo.begin_inplace_commit(
                con, run_id=stan.run_id, commit_id=stan.commit_id, location_id=location_id,
                hdu_index=loc["hdu_index"], header_text=backup_text, spec=spec, now=stan.clock(),
                pending_ids=tuple(r["id"] for r in rows))

        def phase(self, faza, reason=None):
            repo.set_inplace_op_phase(con, op_id=self.op_id, phase=faza, now=now,
                                      reason=reason, expect_phase="writing")

    def _straz():
        return repo.guard_file_replace(con, location_id=location_id, generation=gen)

    droga = None                                 # powód drogi atomowej w trybie `inplace`
    res = None
    dziennik = _Dziennik()
    if inplace:
        res = write_changes_inplace(
            path, ops, expected, journal=dziennik,
            anchor=FileAnchor(loc["file_sha1"], loc["mtime"], strict=not fallback))
        if isinstance(res, Fallback):
            if not fallback:
                res = WriteResult("blocked", PowodPozycji(
                    f"nie mieści się w miejscu (tryb bez spadku): {res.reason}", "no_fallback",
                    detail=res.reason), None)
            else:
                # Kod spadku i szczegół odmowy w miejscu osobno (AR-141): okno zmiany obiektu
                # rozpoznaje spadek po kodzie także w powodzie pozycji zapisanym w bazie.
                droga = PowodPozycji(f"{PREFIKS_DROGI_ATOMOWEJ}: {res.reason}", "inplace_fallback",
                                     detail=res.reason)
                res = None
    if res is None:
        res = write_changes(path, ops, expected, persist_backup=_persist,
                            replace_guard=_straz, confirm_backup=_potwierdz)  # podmiana pod strażą

    if res.code == CODE_POWROT_WYPARTEJ and backup_pliku:
        # C3 (AR-64): podmiana wyparła cudzą wersję - jej powrót przez wspólny automat
        # rekoncyliacji (fazy w osobnych transakcjach, wznawialny po śmierci w każdym kroku).
        # Werdykt automatu jest wynikiem lokacji: plik wraca do cudzej wersji, zmiana NIE zapisana.
        powod = _rekoncyliuj_backupy(con, repo.pending_header_backups(con, location_id),
                                     _location(con, location_id), now=now)
        reason = _dopisz(res.reason, powod)
        # Backup rozstrzygnięty → pod ścieżką nie ma naszej wersji ('blocked'); nadal
        # niepotwierdzony → powrót w toku, pod ścieżką może stać nasza wersja ('failed').
        w_toku = any(z["id"] == backup_pliku[0]
                     for z in repo.pending_header_backups(con, location_id))
        status = "failed" if w_toku else "blocked"
        if w_toku:
            # Podmiana zaszła - spadek na drogę atomową jest faktem o pliku niezależnie od statusu
            # (AR-161): uwaga drogi idzie za powodem, jak przy zapisie wstrzymanym.
            reason = _dopisz(reason, droga)
        _mark(rows, status, reason)
        return _ZapisLokacji(FileResult(location_id, path, status, reason), dotknieto=w_toku)
    if res.backup_text is None:       # zapisu nie było: odmowa albo awaria przed plikiem
        status = "blocked" if res.status == "blocked" else "failed"
        reason = res.reason
        if backup_pliku and status == "blocked":
            # Backup leży, a 'blocked' po nim daje WYŁĄCZNIE odmowa straży podmiany albo
            # rewalidacja po wyparciu, która oddała plik innemu pisarzowi (bramki pisarza stoją
            # przed backupem): pod ścieżką nie ma naszej wersji - cofnięcie go pominie.
            repo.mark_backup_unreplaced(con, backup_id=backup_pliku[0], now=now)
        elif backup_pliku:
            # 'failed' po backupie = wyjątek przy samej podmianie: na zerwanym udziale podmiana
            # mogła zajść mimo błędu. Backup zostaje NIEPOTWIERDZONY (AR-40) - następny commit
            # albo cofnięcie tej lokacji najpierw rozstrzyga go z dyskiem.
            reason = PowodPozycji(f"{res.reason}; podmiana niepotwierdzona, backup do cofnięcia "
                                  f"zapisany w commicie {stan.commit_id}", "replace_unconfirmed",
                                  inner=res.reason, commit_id=stan.commit_id)
        _mark(rows, status, reason)
        return _ZapisLokacji(FileResult(location_id, path, status, reason, code=res.code),
                             dotknieto=bool(backup_pliku) and status == "failed")
    stan.podmieniono = True
    if res.status != "applied":
        # Backup JEST (powstał przed zapisem), więc undo cofnie plik, o ile leży na nim to, co
        # zapisaliśmy (`post_hash`); plik rozdarty w miejscu naprawia `recover_torn`. Re-syncu
        # NIE robimy - baza opisuje bajty POTWIERDZONE. Nagrobek ręki też zostaje.
        if res.in_place:
            reason = PowodPozycji(
                f"{res.reason}; backup do cofnięcia zapisany w commicie {stan.commit_id}; lokacja "
                f"IZOLOWANA od skanu, odzysk: {_droga_przywroc(dziennik.op_id)}",
                "backup_saved_in_isolated", inner=res.reason, commit_id=stan.commit_id,
                way=_droga_przywroc(dziennik.op_id))
        else:
            # Droga atomowa: plik PODMIENIONY - spadek z zapisu w miejscu (AR-161) idzie uwagą za
            # powodem, żeby zdanie okna policzyło przepisany plik także przy 'failed'.
            reason = _dopisz(PowodPozycji(f"{res.reason}; backup do cofnięcia zapisany w commicie "
                                          f"{stan.commit_id}", "backup_saved_in", inner=res.reason,
                                          commit_id=stan.commit_id), droga)
        _mark(rows, "failed", reason)
        return _ZapisLokacji(FileResult(location_id, path, "failed", reason), dotknieto=True)
    if res.in_place:
        # PLIK→DB pod blokadą: region == wynik, kontrola danych (bajty poza nagłówkiem), re-sync
        # i JEDNA transakcja zamknięcia (`synced` + wpisy 'applied' + nagrobek). Porażka zostawia
        # lokację IZOLOWANĄ w fazie `written` (skan jej nie ruszy, a nie „naprawi ponownym
        # re-skanem") - drogę dalej (`finish_inplace` / `recover_torn`) niesie powód.
        koniec = _dokoncz(con, dziennik.op_id, now=now)
        if koniec.status != "applied":
            # Zwolnienie ręką = gest okna albo rdzeń pod blokadą pliku (`release_isolation`),
            # nie klinga bazy. Powód, który już niesie drogę wyjścia (odzysk albo receptę ręczną),
            # drugiej nie dostaje - rozpoznanie po KODZIE fragmentu `way_*` (AR-148).
            if koniec.status == "failed" or _niesie_droge(koniec.reason):
                reason = PowodPozycji(f"{koniec.reason}; backup do cofnięcia zapisany w commicie "
                                      f"{stan.commit_id}; lokacja IZOLOWANA od skanu",
                                      "finish_failed_isolated", inner=koniec.reason,
                                      commit_id=stan.commit_id)
            else:
                reason = PowodPozycji(
                    f"{koniec.reason}; backup do cofnięcia zapisany w commicie {stan.commit_id}; "
                    f"lokacja IZOLOWANA od skanu, zwolnienie ręką: w Zbiorach z menu prawego kliku "
                    f"„{_GEST_ZWOLNIJ}” albo writeback.release_isolation({dziennik.op_id})",
                    "finish_failed_isolated_release", inner=koniec.reason,
                    commit_id=stan.commit_id, op_id=dziennik.op_id)
            _mark(rows, "failed", reason)
            return _ZapisLokacji(FileResult(location_id, path, "failed", reason), dotknieto=True)
        if koniec.code == CODE_ZEZNANIE_WSTRZYMANE:
            # AR-82: faza domknięta, plik zgodny, a zeznanie klatki nie przyjęło zapisu - wpisy
            # 'failed' z wiązaniem wstrzymania i nagrobek zostawiło dokończenie, atomowo z fazą.
            return _ZapisLokacji(FileResult(location_id, path, "withheld",
                                            _dopisz(koniec.reason, droga),
                                            code=CODE_ZEZNANIE_WSTRZYMANE), dotknieto=True)
        # Wpisy stagingu i nagrobek zamknęło dokończenie, atomowo z fazą (powód Z8, gdy nagrobek
        # został mimo karty `OBJECT`).
        return _ZapisLokacji(FileResult(location_id, path, "applied",
                                        _dopisz(droga, koniec.reason)), w_miejscu=True,
                             dotknieto=True)
    # NAGROBEK RĘKI GAŚNIE TU, a nie w ścieżce skanu (S2b, §4/14b-c). Klatka cofnięta ma
    # `object_source='user_cleared'` i drabina ją POMIJA - bez tego gestu zostałaby poza osią na
    # zawsze, nawet po dopisaniu karty. Wyzwalaczem jest WPISANIE `OBJECT` do TEGO pliku, nie
    # samo odświeżenie zeznania: każdy skan odświeża zeznanie i gasiłby werdykt, którego nikt
    # nie odwołał. Droga w miejscu gasi go tą samą klingą w transakcji dokończenia
    # (`repo.finish_inplace_op`); commit 'failed', którego bajty potwierdzi późniejszy skan,
    # dokańcza `repo.confirm_failed_commit_by_scan`.
    # Zgaszenie niesie commit i plik (AR-38) - cofnięcie TEGO commitu odtworzy nagrobek.
    # Wciągnięcie rekordu, zgaszenie i wpisy 'applied' idą JEDNĄ transakcją (AR-38 (2)):
    # awaria między nimi zostawiała kartę w bazie przy żywym nagrobku i wpisach 'pending'.
    # ZEZNANIE WSTRZYMANE (AR-82): bez dowodu, że zeznanie klatki przyjęło zapisany nagłówek, ta
    # sama transakcja zakłada wstrzymanie (wpisy 'failed' z wiązaniem, wersja decyzji ręki z backupu)
    # i nagrobek zostaje - zgasi go dopiero dokończenie przy tej samej wersji decyzji ręki.
    wstrzymanie: list[str] = []
    nagrobek: list[str] = []          # powód, czemu nagrobek ręki został mimo karty `OBJECT` (Z8)

    def _zamknij(zeznanie):
        if not zeznanie:
            powod = repo.withheld_reason(con, location_id=location_id, commit_id=stan.commit_id)
            # Pozycja gestu dostaje w TEJ transakcji powód wyniku lokacji - z uwagą o spadku na
            # drogę atomową (AR-141: okno z Porządków mówi to samo, co okno po biegu).
            repo.withhold_write(con, kind="commit", location_id=location_id,
                                commit_id=stan.commit_id, header_hash=res.post_hash,
                                reason=powod, now=now, pending_ids=[r["id"] for r in rows],
                                backup_id=backup_pliku[0], item_note=droga)
            wstrzymanie.append(powod)
            return
        uwaga = None
        if any(op.keyword == "OBJECT" for op in ops):
            # Z8: tylko przy wersji decyzji ręki z backupu (sprzed pierwszego bajtu) - decyzja
            # człowieka z okna zapis → re-sync zostaje, a powód wpisów i wyniku to mówi.
            uwaga = repo.clear_tombstone_after_write(
                con, frame_id=loc["frame_id"], backup_id=backup_pliku[0],
                commit_id=stan.commit_id, location_id=location_id, now=now)
        _mark(rows, "applied", uwaga)
        if uwaga is not None:
            nagrobek.append(uwaga)

    try:                              # droga atomowa: PLIK→DB (T8); pełny odczyt pliku
        niezgodne = _resync(con, path, loc["volume"], now=now,
                            expect_sha1_data=loc["sha1_data"], w_transakcji=_zamknij).niezgodne
    except Exception as exc:  # noqa: BLE001 - plik zapisany, pętla idzie dalej
        # Wsad to tysiące pełnych odczytów po SMB - jedna czkawka udziału nie może zatrzymać
        # przebiegu z plikiem zapisanym, a bez statusu. Bazę drogi atomowej naprawi ponowny
        # re-skan (T8) - ta droga lokacji nie izoluje.
        blad = _blad_systemu(exc)
        niezgodne = PowodPozycji(f"plik ZMIENIONY, ale re-sync padł - {blad}", "resync_failed",
                                 detail=blad)
    if niezgodne is not None:
        reason = _dopisz(PowodPozycji(f"{niezgodne}; backup do cofnięcia zapisany w commicie "
                                      f"{stan.commit_id}", "backup_saved_in", inner=niezgodne,
                                      commit_id=stan.commit_id), droga)    # spadek (AR-161)
        _mark(rows, "failed", reason)
        return _ZapisLokacji(FileResult(location_id, path, "failed", reason), dotknieto=True)
    if wstrzymanie:
        return _ZapisLokacji(FileResult(location_id, path, "withheld",
                                        _dopisz(wstrzymanie[0], droga),
                                        code=CODE_ZEZNANIE_WSTRZYMANE), dotknieto=True)
    return _ZapisLokacji(FileResult(location_id, path, "applied",
                                    _dopisz(_dopisz(droga, res.reason),
                                            nagrobek[0] if nagrobek else None),
                                    code=CODE_INPLACE_FALLBACK if droga is not None else None),
                         dotknieto=True)


# ============================================================ RENAME "Nazwy z faktów" (trzecia operacja)
# Rename PLIKU = mutacja → mieszka w tej klindze (jak os.replace writebacku). Prymityw `os.rename`
# (NIE `os.replace`): na Windows (tor R:/NAS) rzuca `FileExistsError` gdy cel istnieje = twardy backstop.
# Anty-clobber DWUWARSTWOWY (R3 #1/#3): (1) `os.path.exists(new)` — brama PRZENOŚNA (na POSIX `os.rename`
# CICHO nadpisuje, więc rename-fail sam nie wystarcza - R3-P2 #3); (2) straż `repo.guard_file_rename`
# re-sprawdza `UNIQUE(volume,new_path)` pod blokadą zapisu bazy. Commit i undo idą przez `_rename_pod_straza`:
# DB/dysk-check → trwały zamiar (`pending_renames.in_flight`, zatwierdzony PRZED mutacją) → w jednej
# transakcji straż izolacji i generacji → `os.rename` → UPDATE path + event + status wiersza. Awaria
# między `os.rename` a COMMIT: kompensacja `new→old`, a gdy ona też nie wyjdzie - zamiar zostaje
# i `reconcile_renames` przepina TĘ SAMĄ lokację tam, gdzie plik stoi (AR-29). Wiersz 'applied' sam
# jest rekordem undo.
# `os.rename` żyje TU (meta-test: `rename` ∈ OS_MUTATORS, DOOR=writeback.py).


@dataclasses.dataclass(frozen=True)
class RenameFileResult:
    status: str            # 'applied' | 'blocked' | 'failed'
    reason: str | None
    # Rozdarcie plik↔baza bez kompensacji: plik pod nową nazwą, baza pod starą, zamiar renamu otwarty
    # dla rekoncyliacji (AR-29). Fałsz = plik stoi tam, gdzie baza.
    torn: bool = False


def rename_file(old_path, new_path) -> RenameFileResult:
    """Prymityw renamu pliku (KLINGA). Brama anty-clobber: źródło istnieje ORAZ cel NIE istnieje na
    dysku (przenośne) → `os.rename` (Windows: `FileExistsError` przy wyścigu = backstop). Rename w tym
    samym katalogu = atomowy na wolumenie. Zwraca status; wołający (`commit_renames`) mapuje na staging.

    PLIK ZAJĘTY (AR-125, `_RENAME_ZAJETY`: antywirus, indeksowanie, Eksplorator po założeniu katalogu)
    → krótkie ponowienie `_PODMIANA_PONOWIENIA`, wyłącznie gdy plik stoi na miejscu (`_na_miejscu`);
    brama anty-clobber przed KAŻDĄ próbą. Odmowa 'blocked' zapada tylko przed pierwszym `os.rename` -
    po nieudanej próbie brama, która nie przechodzi, oddaje 'failed' z ostatnim błędem, bo plik mógł
    przejść mimo błędu klienta SMB, a o tym rozstrzyga wołający z dysku (`_przeszedl`)."""
    old_path = os.fspath(old_path)
    new_path = os.fspath(new_path)
    blad = None
    for proba, pauza in enumerate((*_PODMIANA_PONOWIENIA, None), start=1):
        try:
            if blad is None and not os.path.exists(old_path):
                return RenameFileResult("blocked", PowodPozycji("źródło nie istnieje na dysku",
                                                                "src_missing"))
            if blad is None and os.path.exists(new_path):
                return RenameFileResult("blocked", PowodPozycji(
                    "cel już istnieje na dysku (anty-clobber)", "dst_exists"))
            if blad is not None and not _na_miejscu(old_path, new_path):
                return RenameFileResult("failed", _powod_bledu_renamu(blad, proba - 1))
            os.rename(old_path, new_path)
            return RenameFileResult("applied", None)
        except Exception as exc:  # noqa: BLE001 — raport zamiast wyjątku w warstwie zapisu
            blad = exc
            if (pauza is None or getattr(exc, "winerror", None) not in _RENAME_ZAJETY
                    or not _na_miejscu(old_path, new_path)):
                return RenameFileResult("failed", _powod_bledu_renamu(exc, proba))
            time.sleep(pauza)
    raise AssertionError("pętla ponowień renamu wyszła bez wyniku")


def _powod_bledu_renamu(exc, prob: int) -> str:
    """Powód porażki prymitywu renamu: plik zajęty zdaniem z receptą, każdy inny błąd klasą
    systemu albo - spoza klas - tekstem systemu (`_blad_systemu`, AR-168)."""
    kod = getattr(exc, "winerror", None)
    if kod in _RENAME_ZAJETY:
        return PowodPozycji(f"plik zajęty przez inny program (WinError {kod}, prób: {prob}) - "
                            f"spróbuj ponownie za chwilę", "busy", winerror=kod, tries=prob)
    return _blad_systemu(exc)


def renames_for_run(con, run_id):
    """Wpisy stagingu renamu przebiegu (commit + szuflada GUI). Kolejność `id` = kolejność stagingu."""
    return con.execute(
        "SELECT id, location_id, old_path, new_path, expected_mtime, status, reason, in_flight "
        "FROM pending_renames WHERE run_id = ? ORDER BY id",
        (run_id,),
    ).fetchall()


def open_rename_intents(con):
    """Wiersze stagingu z otwartym zamiarem renamu (AR-29), wszystkich przebiegów. Zbiór mały
    z definicji (tylko próby przerwane awarią), więc rekoncyliacja nie stat-uje całego archiwum."""
    return con.execute(
        "SELECT id, run_id, location_id, old_path, new_path, status, in_flight "
        "FROM pending_renames WHERE in_flight IS NOT NULL ORDER BY id").fetchall()


def _location_rename(con, location_id):
    """Wiersz location do renamu: id, volume, path, mtime, present (kotwica anty-stale)."""
    return con.execute(
        "SELECT id, volume, path, mtime, present, file_sha1 FROM location WHERE id = ?",
        (location_id,),
    ).fetchone()


class _RenameNieZaszedl(Exception):
    """Prymityw renamu odmówił albo padł wewnątrz straży relokacji - wyjątek przerywa jej transakcję
    (rollback, zero UPDATE) i niesie wynik prymitywu do wołającego."""

    def __init__(self, wynik: RenameFileResult):
        super().__init__(wynik.reason)
        self.wynik = wynik


def _powod_konfliktu_renamu(op) -> str:
    """Powód odmowy renamu pod strażą relokacji (`repo.InplaceConflict`)."""
    if op["phase"] in repo.INPLACE_ISOLATING_PHASES:
        return _powod_izolacji(op)
    return PowodPozycji(
        f"lokacja dostała zapis w miejscu (operacja {op['id']}, {op['kind']}, faza {op['phase']}) "
        f"po bramce renamu - nagłówek, z którego pochodzi nowa nazwa, mógł się zmienić; renamu nie "
        f"było, plik nietknięty - odśwież podgląd nazw", "inplace_after_gate", op_id=op["id"],
        op_kind=op["kind"], phase=op["phase"])


def _przeszedl(src, dst) -> bool:
    """Plik stoi pod `dst`, a `src` go nie ma - rename zaszedł. Na udziale SMB `os.rename` potrafi
    rzucić po stronie klienta, choć serwer przeniósł plik; o tym, gdzie plik jest, mówi dysk."""
    try:
        return os.path.exists(dst) and not os.path.exists(src)
    except OSError:
        return False


def _na_miejscu(src, dst) -> bool:
    """POZYTYWNY dowód, że rename NIE zaszedł: plik pod `src`, `dst` wolne. Udział, który nie
    odpowiada, daje `exists() == False` dla obu nazw - to nie jest dowód, tylko brak wiedzy."""
    try:
        return os.path.exists(src) and not os.path.exists(dst)
    except OSError:
        return False


def _po_awarii_przepiecia(con, *, rename_id, location_id, src, dst, kierunek,
                          exc) -> RenameFileResult:
    """`os.rename(src, dst)` zaszedł, transakcja przepięcia bazy padła (UPDATE, status albo COMMIT).
    KOMPENSACJA `dst→src` wyłącznie, gdy baza POTWIERDZA, że przepięcie nie weszło (`path == src`),
    a zamiar tej próby (`kierunek`) jest wciąż otwarty: gdyby COMMIT zdążył się utrwalić albo
    rekoncyliacja innego procesu przepięła bazę na `dst`, cofnięcie pliku rozdarłoby to, co jest
    spójne. Plik wrócił → zamiar gaśnie, wiersz zostaje do ponowienia. Kompensacja niemożliwa albo
    baza milczy → zamiar ZOSTAJE ('torn'), a `reconcile_renames` przy ponowieniu, cofnięciu albo
    wejściu do etapu przepina tę samą lokację tam, gdzie plik stoi.

    JEDNA BLOKADA (AR-56, `repo.guard_rename_compensation`): odczyt bazy, powrót pliku i zgaszenie
    zamiaru idą pod jednym `BEGIN IMMEDIATE`. Dawniej odczyt `path` i powrót pliku to były dwie
    chwile - rekoncyliacja innego procesu mogła między nimi przepiąć bazę na `dst` i zgasić zamiar,
    a plik wracał pod `src`: baza na `dst`, plik na `src`, zamiaru brak."""
    blad = _blad_systemu(exc)
    wrocil = False
    try:
        if con.in_transaction:                    # COMMIT, który rzucił, mógł zostawić transakcję
            con.rollback()
        with repo.guard_rename_compensation(con, rename_id=rename_id,
                                            location_id=location_id) as stan:
            if stan.path == dst:                  # przepięcie jednak weszło - stan spójny
                return RenameFileResult("applied", None)
            if stan.path != src or stan.in_flight != kierunek:
                return RenameFileResult(
                    "failed", PowodPozycji(
                        f"plik PRZENIESIONY na {dst}, baza NIE przepięta ({blad}), a zamiar tej "
                        f"próby rozstrzygnął inny proces (baza: {stan.path}, zamiar: "
                        f"{stan.in_flight}) - kompensacji nie ma; sprawdź, gdzie stoi plik",
                        "torn_other", dst=dst, detail=blad, db_path=stan.path,
                        in_flight=stan.in_flight),
                    torn=True)
            cofniety = rename_file(dst, src)
            if cofniety.status != "applied":
                raise _RenameNieZaszedl(cofniety)
            wrocil = True
            stan.zgas = True
    except Exception as exc2:  # noqa: BLE001 - baza milczy albo plik nie wrócił; zamiar zostaje
        if wrocil:
            blad_zamiaru = _blad_systemu(exc2)
            return RenameFileResult("failed", PowodPozycji(
                f"baza nie przyjęła przepięcia ({blad}) - plik wrócił pod nazwę {src}, ale zamiar "
                f"renamu nie zgaszony ({blad_zamiaru}) - rekoncyliacja go zamknie",
                "returned_intent_left", detail=blad, src=src, intent_detail=blad_zamiaru))
        return RenameFileResult("failed", PowodPozycji(
            f"plik PRZENIESIONY na {dst}, ale baza NIE przepięta ({blad}) - zamiar renamu zapisany: "
            f"ponowienie albo cofnięcie przebiegu dokończy przepięcie", "torn_db_not", dst=dst,
            detail=blad), torn=True)
    return RenameFileResult("failed", PowodPozycji(
        f"baza nie przyjęła przepięcia ({blad}) - plik wrócił pod nazwę {src}; renamu nie ma, "
        f"można ponowić", "returned", detail=blad, src=src))


def _rename_pod_straza(con, *, rename_id, kierunek, location_id, old_path, new_path, generation,
                       now, status, reason=None, gest=None) -> RenameFileResult:
    """RENAME I RELOKACJA W JEDNEJ TRANSAKCJI (`repo.guard_file_rename`, AR-17 (5)): pod blokadą
    zapisu bazy lokacja bez operacji izolującej i bez operacji nowszej niż `generation` (zapamiętanej
    PRZED bramką izolacji wołającego), cel wolny w bazie, potem `rename_file` (`os.rename`) i dopiero
    po nim UPDATE `location.path` z eventem oraz `status`/`reason` wiersza stagingu `rename_id`
    (AR-29 (2)). Między bramką izolacji a `os.rename` zapis w miejscu mógł otworzyć operację na tym
    pliku - wtedy 'blocked', renamu nie było. `old_path`/`new_path` = kierunek TEJ próby (undo podaje
    je odwrotnie), `kierunek` ('commit'|'undo') trafia do zamiaru.

    TRWAŁY ZAMIAR (AR-29 (1)): `repo.open_rename_intent` zatwierdza próbę PRZED `os.rename`. Plik
    nie ruszył się (odmowa prymitywu, straż, anty-clobber) → zamiar gaśnie. Sukces → gaśnie w tej
    samej transakcji co relokacja. Wyjątek po udanym renamie → `_po_awarii_przepiecia` (kompensacja
    albo zamiar zostaje dla `reconcile_renames`). `gest` trafia do ładunku `location.renamed`
    (`repo._apply_relocation`) - przeniesienie zmiany obiektu, nie zmiana nazwy."""
    try:
        repo.open_rename_intent(con, rename_id=rename_id, direction=kierunek)
    except Exception as exc:  # noqa: BLE001 - bez zamiaru nie ruszamy pliku
        blad = _blad_systemu(exc)
        return RenameFileResult("failed", PowodPozycji(
            f"zamiar renamu nie zapisany ({blad}) - renamu nie było, plik nietknięty",
            "intent_not_saved", detail=blad))
    przeniesiony = False
    try:
        with repo.guard_file_rename(con, location_id=location_id, new_path=new_path,
                                    generation=generation, now=now, rename_id=rename_id,
                                    status=status, reason=reason, kierunek=kierunek, gest=gest):
            wynik = rename_file(old_path, new_path)            # tu następuje os.rename
            if wynik.status == "failed" and _przeszedl(old_path, new_path):
                wynik = RenameFileResult("applied", None)      # błąd klienta SMB, plik przeszedł
            if wynik.status != "applied":
                raise _RenameNieZaszedl(wynik)
            przeniesiony = True
    except Exception as exc:  # noqa: BLE001 - raport zamiast wyjątku w warstwie zapisu
        if przeniesiony:
            return _po_awarii_przepiecia(con, rename_id=rename_id, location_id=location_id,
                                         src=old_path, dst=new_path, kierunek=kierunek, exc=exc)
        # Odmowa straży i prymitywu ('blocked') zapada PRZED `os.rename`; porażka samego renamu albo
        # wyjątek spoza straży mogły zajść PO nim (serwer SMB przeniósł plik, klient dostał błąd,
        # udział zamilkł). Zamiar gaśnie wyłącznie przy dowodzie, że plik stoi pod starą nazwą.
        przed_renamem = isinstance(exc, (repo.InplaceConflict, ValueError)) or (
            isinstance(exc, _RenameNieZaszedl) and exc.wynik.status != "failed")
        if not przed_renamem and not _na_miejscu(old_path, new_path):
            powod = exc.wynik.reason if isinstance(exc, _RenameNieZaszedl) else \
                _blad_systemu(exc)
            return RenameFileResult("failed", PowodPozycji(
                f"stan pliku nieznany po błędzie renamu ({powod}) - zamiar renamu zostaje: "
                f"ponowienie albo cofnięcie przebiegu rozstrzygnie, gdzie plik stoi",
                "torn_unknown", inner=powod), torn=True)
        try:
            repo.drop_rename_intent(con, rename_id=rename_id)
        except Exception:  # noqa: BLE001 - plik nietknięty; zamiar zgasi rekoncyliacja
            pass
        if isinstance(exc, _RenameNieZaszedl):
            return exc.wynik
        if isinstance(exc, repo.InplaceConflict):
            return RenameFileResult("blocked", _powod_konfliktu_renamu(exc.op))
        if isinstance(exc, ValueError):                        # anty-clobber w bazie pod blokadą
            return RenameFileResult("blocked", powod_wyjatku(exc))
        return RenameFileResult("failed", _blad_systemu(exc))
    return RenameFileResult("applied", None)


_COFNIETO = PowodPozycji("cofnięto (undo)", "rename_undone")
_ZAMIAR_OTWARTY = PowodPozycji("przerwany rename tego pliku czeka na rozstrzygnięcie (zamiar "
                               "otwarty) - powód w wyniku rekoncyliacji", "rename_open")


def reconcile_renames(con, *, now, volume=None) -> list[FileResult]:
    """REKONCYLIACJA ZAMIARÓW RENAMU (AR-29): każdy wiersz z otwartym `in_flight` (próba przerwana
    awarią albo śmiercią procesu między `os.rename` a COMMIT) dostaje bazę tam, gdzie plik FAKTYCZNIE
    stoi - przez przepięcie TEJ SAMEJ lokacji (`location.renamed` z powodem), nigdy przez nową
    lokację. Ruchu pliku tu nie ma: plik jest prawdą, baza go dogania.

    Rozstrzyga dysk: plik pod dokładnie jedną z nazw pary. Tożsamość pliku pod nową dla bazy nazwą
    = `mtime` równy kopii (rename nie tyka treści ani `mtime`; rozmiar w astro nie rozróżnia klatek),
    a sama nazwa pochodzi z zamiaru zapisanego przed próbą. Status wiersza wynika z miejsca pliku:
    pod `new_path` → 'applied' (cofnięcie go obejmie); pod `old_path` → 'skipped' po cofnięciu albo
    'pending' po commicie (ponowienie go obejmie).

    Zostawia zamiar i melduje 'blocked', gdy: plik pod obiema nazwami albo pod żadną, `mtime` inny
    niż kopii (to może nie być ten plik), cel zajęty w bazie przez INNĄ lokację (skan zdążył wciągnąć
    plik jako nową kopię - recepta w powodzie). Zwraca `FileResult` per zamiar ('reconciled' z opisem
    albo 'blocked' z powodem). Zbiór zamiarów jest mały z definicji, więc wołanie na wejściu etapu
    kosztuje jedno zapytanie, gdy nic nie przerwano. `volume` zawęża do zamiarów lokacji tego
    woluminu (skan rozstrzyga tylko to, co sam mógłby wciągnąć); wyjątek jednego zamiaru → 'blocked'."""
    wyniki = []
    for r in open_rename_intents(con):
        if volume is not None:
            loc = _location_rename(con, r["location_id"])
            if loc is not None and loc["volume"] != volume:
                continue                          # cudzy wolumin - litera ścieżki nie dowodzi tożsamości
        try:
            wyniki.append(_rozstrzygnij_zamiar(con, r, now=now))
        except Exception as exc:  # noqa: BLE001 - jeden zamiar nie przerywa etapu, w którym go liczymy
            blad = _blad_systemu(exc)
            wyniki.append(FileResult(r["location_id"], r["old_path"], "blocked", PowodPozycji(
                f"rekoncyliacja padła ({blad}) - zamiar zostaje", "reconcile_failed",
                detail=blad)))
    return wyniki


# Celowo INNE zdanie niż `_BRAK_LOCATION` („brak location w bazie”, kod `no_location`): rekoncyliacja
# renamu mówi tak od zawsze, a proza zostaje znak w znak - stąd osobny kod.
_BRAK_LOCATION_WIERSZA = PowodPozycji("brak location", "no_location_row")


def _dysk_milczy(exc) -> PowodPozycji:
    """Powód rekoncyliacji zamiaru, gdy dysk nie odpowiada na pytanie o plik - zamiar zostaje."""
    blad = _blad_systemu(exc, z_typem=False)
    return PowodPozycji(f"dysk nie odpowiada ({blad}) - zamiar zostaje", "disk_silent", detail=blad)


def _rozstrzygnij_zamiar(con, r, *, now) -> FileResult:
    rid, lid, stara, nowa = r["id"], r["location_id"], r["old_path"], r["new_path"]
    loc = _location_rename(con, lid)
    if loc is None:
        repo.settle_rename_intent(con, rename_id=rid, location_id=lid, status="failed",
                                  reason=_BRAK_LOCATION_WIERSZA, now=now)
        return FileResult(lid, stara, "reconciled", PowodPozycji(
            "brak location - zamiar zamknięty", "intent_closed_no_location"))
    try:
        pod_stara, pod_nowa = os.path.exists(stara), os.path.exists(nowa)
    except OSError as exc:
        return FileResult(lid, stara, "blocked", _dysk_milczy(exc))
    if pod_stara == pod_nowa:
        if pod_stara:
            return FileResult(lid, stara, "blocked", PowodPozycji(
                f"plik pod obiema nazwami ({stara} / {nowa}) - zamiar zostaje, rozstrzyga człowiek",
                "intent_both_names", src=stara, dst=nowa))
        return FileResult(lid, stara, "blocked", PowodPozycji(
            f"plik pod żadną z nazw ({stara} / {nowa}) - zamiar zostaje, rozstrzyga człowiek",
            "intent_no_name", src=stara, dst=nowa))
    tam = nowa if pod_nowa else stara
    if tam == nowa:
        status, powod = "applied", None
    elif r["in_flight"] == "undo":
        status, powod = "skipped", _COFNIETO
    else:
        status, powod = "pending", None
    relocate_to = None
    if loc["path"] != tam:
        try:
            mtime = scan._mtime_iso(os.stat(tam))
        except OSError as exc:
            return FileResult(lid, tam, "blocked", _dysk_milczy(exc))
        if loc["mtime"] is None or mtime != loc["mtime"]:
            return FileResult(lid, tam, "blocked", PowodPozycji(
                f"plik pod {tam} ma mtime {mtime}, kopia w bazie {loc['mtime']} - to może nie być "
                f"ten plik; zamiar zostaje, rozstrzyga człowiek", "intent_mtime_differs", path=tam,
                mtime=mtime, db_mtime=loc["mtime"]))
        # `mtime` da się przenieść kopiowaniem, treści nie: zamiarów jest garstka, więc pełny odczyt
        # pliku jest tani wobec przepięcia lokacji na obcy plik.
        if loc["file_sha1"] is not None:
            try:
                sha = hashing.sha1_of(tam)
            except OSError as exc:
                return FileResult(lid, tam, "blocked", _dysk_milczy(exc))
            if sha != loc["file_sha1"]:
                return FileResult(lid, tam, "blocked", PowodPozycji(
                    f"plik pod {tam} ma inną treść niż kopia w bazie (sha1) - to nie jest ten plik; "
                    f"zamiar zostaje, rozstrzyga człowiek", "intent_sha1_differs", path=tam))
        relocate_to = tam
    inna = stara if tam == nowa else nowa

    def _wciaz_tam():
        # Pod blokadą zapisu bazy (AR-56): kompensacja innego procesu przenosi plik i gasi zamiar
        # w tej samej blokadzie - obserwacja sprzed niej musi się powtórzyć.
        return os.path.exists(tam) and not os.path.exists(inna)
    try:
        repo.settle_rename_intent(con, rename_id=rid, location_id=lid, status=status, reason=powod,
                                  now=now, relocate_to=relocate_to, expect_in_flight=r["in_flight"],
                                  potwierdz=_wciaz_tam)
    except repo.RenameIntentChanged as exc:
        zmiana = powod_wyjatku(exc)
        return FileResult(lid, tam, "blocked", PowodPozycji(
            f"{zmiana} - nic nie zmieniono, następna rekoncyliacja zobaczy stan bieżący",
            "intent_changed", inner=zmiana))
    except ValueError as exc:                     # cel zajęty w bazie przez inną lokację
        zajety = powod_wyjatku(exc)
        return FileResult(lid, tam, "blocked", PowodPozycji(
            f"{zajety} - skan wciągnął plik jako nową kopię; zamiar zostaje (lokacja {lid} pod "
            f"{loc['path']} niesie historię renamu)", "intent_target_taken", inner=zajety,
            location=lid, path=loc["path"]))
    if relocate_to:
        return FileResult(lid, tam, "reconciled", PowodPozycji(
            f"baza przepięta na {tam}", "reconciled_relocated", path=tam))
    return FileResult(lid, tam, "reconciled", PowodPozycji(
        f"baza zgodna z plikiem ({tam})", "reconciled_in_sync", path=tam))


def commit_renames(con, run_id, *, now,
                   progress: Callable[[int, int, str, str], None] | None = None,
                   should_cancel: Callable[[], bool] | None = None) -> CommitResult:
    """Zapisz `pending_renames` (status 'pending') przebiegu na dysk. Per wiersz: kotwica (present +
    `mtime`==staged + `path`==`old_path` + brak wiersza `location(volume,new_path)` - R3 #3) →
    `rename_file` (`os.rename`, anty-clobber dyskowy R3 #1) i UPDATE `location.path` z eventem (NIE
    ingest - R2 #1) w JEDNEJ transakcji straży relokacji (`_rename_pod_straza`: bramka izolacji
    i generacji zapisu w miejscu powtórzona pod blokadą bazy, AR-17 (5)). Kotwica-mtime niezmienna po
    renamie (rename nie tyka treści), więc re-commit po udanym renamie widzi już `path==new_path`.
    Utrwalanie per plik (funkcje `repo` commitują), więc anulowanie zostawia zrobione 'applied', resztę
    'pending'. `progress(done, total, path, status)` po KAŻDYM pliku (Qt-wolne). Zwraca `CommitResult`
    (`commit_id` zawsze None - rename bez tabeli commitów; wiersz 'applied' sam jest undo-rekordem).

    Na wejściu `reconcile_renames` (AR-29): przerwane próby WSZYSTKICH przebiegów dostają bazę tam,
    gdzie stoi plik, zanim ten przebieg zacznie liczyć kotwice; wynik w `CommitResult.reconciled`.
    Wiersz, którego zamiaru rekoncyliacja nie rozstrzygnęła, jest 'blocked' bez zmiany statusu."""
    reconciled = reconcile_renames(con, now=now)
    pending = [r for r in renames_for_run(con, run_id) if r["status"] == "pending"]
    total = len(pending)
    applied: list[FileResult] = []
    blocked: list[FileResult] = []
    failed: list[FileResult] = []
    skipped: list[FileResult] = []
    cancelled = False
    done = 0

    def _report(path, status):
        nonlocal done
        done += 1
        if progress is not None:
            progress(done, total, path, status)

    for r in pending:
        if should_cancel is not None and should_cancel():
            cancelled = True
            break
        rid, location_id, old_path, new_path = r["id"], r["location_id"], r["old_path"], r["new_path"]
        if r["in_flight"] is not None:     # zamiar przerwanej próby nierozstrzygnięty - nie ruszamy
            blocked.append(FileResult(location_id, old_path, "blocked", _ZAMIAR_OTWARTY))
            _report(old_path, "blocked")
            continue
        loc = _location_rename(con, location_id)
        if loc is None:
            repo.set_rename_status(con, rename_id=rid, status="failed",
                                   reason=_BRAK_LOCATION_WIERSZA)
            failed.append(FileResult(location_id, old_path, "failed", _BRAK_LOCATION_WIERSZA))
            _report(old_path, "failed")
            continue
        if not loc["present"]:
            reason = _KOPIA_ZNIKNELA
            repo.set_rename_status(con, rename_id=rid, status="skipped", reason=reason)
            skipped.append(FileResult(location_id, old_path, "skipped", reason))
            _report(old_path, "skipped")
            continue
        # Generacja dziennika PRZED bramką: straż relokacji odbije operację zaczętą po tej chwili
        # (`_rename_pod_straza`), także zakończoną, zanim rename się zaczął.
        gen = repo.inplace_generation(con)
        izolujaca = repo.isolating_inplace_op(con, location_id)
        if izolujaca is not None:          # plik po nieukończonym zapisie w miejscu - nie ruszamy
            reason = _powod_izolacji(izolujaca)
            repo.set_rename_status(con, rename_id=rid, status="blocked", reason=reason)
            blocked.append(FileResult(location_id, old_path, "blocked", reason))
            _report(old_path, "blocked")
            continue
        # Kotwica anty-stale: plik nietknięty od podglądu (mtime + ścieżka).
        if loc["mtime"] != r["expected_mtime"] or loc["path"] != old_path:
            reason = PowodPozycji("plik zmieniony od podglądu (mtime/ścieżka)",
                                  "rename_changed_since_preview")
            repo.set_rename_status(con, rename_id=rid, status="blocked", reason=reason)
            blocked.append(FileResult(location_id, old_path, "blocked", reason))
            _report(old_path, "blocked")
            continue
        # Anty-clobber W BAZIE PRZED renamem (R3 #3): brak INNEGO wiersza z celem (torn-state guard).
        db_clash = con.execute(
            "SELECT id FROM location WHERE volume = ? AND path = ? AND id <> ?",
            (loc["volume"], new_path, location_id)).fetchone()
        if db_clash is not None:
            reason = PowodPozycji(f"cel zajęty w bazie (location:{db_clash['id']})", "target_taken",
                                  location=db_clash["id"])
            repo.set_rename_status(con, rename_id=rid, status="blocked", reason=reason)
            blocked.append(FileResult(location_id, old_path, "blocked", reason))
            _report(old_path, "blocked")
            continue

        # Status 'applied' wchodzi w transakcji relokacji (AR-29 (2)) - osobny zapis nie istnieje.
        res = _rename_pod_straza(con, rename_id=rid, kierunek="commit", location_id=location_id,
                                 old_path=old_path, new_path=new_path, generation=gen, now=now,
                                 status="applied")
        if res.status == "applied":
            applied.append(FileResult(location_id, new_path, "applied"))
            _report(new_path, "applied")
        elif res.status == "blocked":
            repo.set_rename_status(con, rename_id=rid, status="blocked", reason=res.reason)
            blocked.append(FileResult(location_id, old_path, "blocked", res.reason))
            _report(old_path, "blocked")
        else:
            repo.set_rename_status(con, rename_id=rid, status="failed", reason=res.reason)
            failed.append(FileResult(location_id, new_path if res.torn else old_path, "failed",
                                     res.reason))
            _report(old_path, "failed")

    return CommitResult(run_id, None, applied, blocked, failed, skipped, cancelled,
                        reconciled=reconciled)


def undo_renames(con, run_id, *, now,
                 progress: Callable[[int, int, str, str], None] | None = None,
                 should_cancel: Callable[[], bool] | None = None) -> UndoResult:
    """Cofnij rename przebiegu: dla wierszy 'applied' odwrotny `os.rename` (new→old) pod TĄ SAMĄ bramą
    anty-clobber i tą samą strażą co commit (`_rename_pod_straza`: izolacja, generacja, cel wolny w bazie,
    relokacja w tej samej transakcji) z powrotem na `old_path`. Kolejność odwrotna (jak stos). Gdy plik
    nie stoi na `new_path` (zmieniony od commitu) → 'blocked'. Udany rewert → status 'skipped' (powód
    „cofnięto") — dwukrotne undo pomija (tylko 'applied' cofane). `commit_id` w wyniku = run przebiegu
    (rename bez tabeli commitów). Bramka bezpieczna per plik.

    Na wejściu `reconcile_renames` (AR-29), jak w `commit_renames`: commit przerwany po `os.rename`
    staje się tu 'applied' (plik pod nową nazwą), więc cofnięcie go obejmuje; wynik w
    `UndoResult.reconciled`. Status 'skipped' wchodzi w transakcji relokacji."""
    reconciled = reconcile_renames(con, now=now)
    applied_rows = [r for r in renames_for_run(con, run_id) if r["status"] == "applied"]
    total = len(applied_rows)
    restored: list[FileResult] = []
    blocked: list[FileResult] = []
    failed: list[FileResult] = []
    cancelled = False
    done = 0

    def _report(path, status):
        nonlocal done
        done += 1
        if progress is not None:
            progress(done, total, path, status)

    for r in reversed(applied_rows):
        if should_cancel is not None and should_cancel():
            cancelled = True
            break
        rid, location_id, old_path, new_path = r["id"], r["location_id"], r["old_path"], r["new_path"]
        if r["in_flight"] is not None:     # zamiar przerwanej próby nierozstrzygnięty - nie ruszamy
            blocked.append(FileResult(location_id, new_path, "blocked", _ZAMIAR_OTWARTY))
            _report(new_path, "blocked")
            continue
        loc = _location_rename(con, location_id)
        if loc is None or loc["path"] != new_path:
            reason = PowodPozycji("plik nie stoi na nazwie z commitu", "not_on_commit_name")
            blocked.append(FileResult(location_id, new_path, "blocked", reason))
            _report(new_path, "blocked")
            continue
        gen = repo.inplace_generation(con)             # PRZED bramką izolacji, jak w `commit_renames`
        izolujaca = repo.isolating_inplace_op(con, location_id)
        if izolujaca is not None:
            blocked.append(FileResult(location_id, new_path, "blocked",
                                      _powod_izolacji(izolujaca)))
            _report(new_path, "blocked")
            continue
        # odwrotny os.rename i relokacja w jednej transakcji pod strażą - to samo okno co przy commicie
        res = _rename_pod_straza(con, rename_id=rid, kierunek="undo", location_id=location_id,
                                 old_path=new_path, new_path=old_path, generation=gen, now=now,
                                 status="skipped", reason=_COFNIETO)
        if res.status == "applied":
            restored.append(FileResult(location_id, old_path, "restored"))
            _report(old_path, "restored")
        elif res.status == "blocked":
            blocked.append(FileResult(location_id, new_path, "blocked", res.reason))
            _report(new_path, "blocked")
        else:
            failed.append(FileResult(location_id, old_path if res.torn else new_path, "failed",
                                     res.reason))
            _report(new_path, "failed")

    return UndoResult(run_id, restored, blocked, failed, cancelled, reconciled=reconciled)


def _ostatnia_operacja(con, commit_id, location_id, kind):
    """Ostatnia operacja `inplace_op` danego rodzaju dla pliku w commicie (albo None)."""
    return con.execute(
        "SELECT * FROM inplace_op WHERE commit_id = ? AND location_id = ? AND kind = ? "
        "ORDER BY id DESC LIMIT 1", (commit_id, location_id, kind)).fetchone()


def _spec_z_operacji(row) -> OpSpec:
    return OpSpec(row["fmt"], row["region_offset"], zlib.decompress(row["old_region_z"]),
                  zlib.decompress(row["new_region_z"]), row["write_start"], row["write_end"],
                  row["file_size"], row["file_ino"], row["pre_hash"], row["post_hash"],
                  row["anchor_sha1"])


def undo(con, commit_id, *, now,
         progress: Callable[[int, int, str, str], None] | None = None,
         should_cancel: Callable[[], bool] | None = None) -> UndoResult:
    """Cofnij commit: przywróć nagłówki z `header_backups` (obsługuje set I add BEZ delete). Po
    udanym zapisie RE-SYNC bazy z kontrolą `sha1_data`. `progress`/`should_cancel` jak w `commit`
    (per plik, granica bezpieczna). Wyjątek re-syncu daje 'failed' dla pliku, pętla idzie dalej.

    DWIE DROGI, WYBÓR Z DZIENNIKA `inplace_op` (astra Z12/Z13):
      * W MIEJSCU (`restore_inplace`) - wyłącznie commit zapisany w miejscu (operacja `commit`
        w fazie `written`/`synced`), backup-koperta, ten sam plik i CAŁY region równy regionowi
        wynikowemu commitu. Cofnięcie ma własną operację `undo` w dzienniku (izolacja + odzysk).
      * ATOMOWO (`write_full_header`) - wszystko inne: stare backupy tekstowe, commity atomowe,
        plik podmieniony od commitu. Plik tymczasowy nie zostawia rozdarcia, więc nie trzeba odzysku.
        Koperta regionu zgodna z układem pliku wraca BAJT W BAJT (AR-19); reszta - semantycznie,
        a taki plik trafia do `UndoResult.semantic` z powodem „cofnięte semantycznie".

    STAN „JUŻ COFNIĘTE" / „ZOSTAŁA SYNCHRONIZACJA":
      * droga w miejscu - z FAZY operacji `undo`: `written` → dokończenie (`_dokoncz`: pod blokadą
        region == wynik cofnięcia i brak nowszej operacji, dopiero wtedy re-sync z kontrolą danych
        → `synced`; inny region → 'blocked', astra 2026-09-27 - dawniej sam re-sync wciągał każdą
        późniejszą zmianę jako cofnięcie), `synced` → 'blocked' „już cofnięte"; operacja otwarta
        (commitu albo cofnięcia) → 'failed' z numerem operacji do odzysku (lokacja izolowana);
        commit w fazie `written` (jego re-sync padł) → najpierw jego dokończenie, potem cofnięcie;
        region na dysku już równy stanowi sprzed commitu (powrót spoza Horreum) - pod jedną
        blokadą dowód CAŁEGO pliku (kontrola danych z kotwicą operacji commitu, AR-169): baza
        opisuje ten plik → 'blocked' „już cofnięte"; baza nie → re-sync z tym samym dowodem; bez
        dowodu (brak kotwicy, bajty poza regionem inne) → 'blocked' z receptą skanu, uchwyt zostaje;
      * droga atomowa (AR-182) - ze ŚLADU własnego cofnięcia (`atomic_undo`, 0044, utrwalony przed
        każdą podmianą cofnięcia) i z pliku: baza wciągnęła wynik własny (ślad z `synced_at`, para
        `location.file_sha1`/`header_hash` = para śladu) i `mtime` pliku jest tym z bazy →
        'blocked' „już cofnięte” BEZ odczytu pliku - ta sama granica zaufania co faza `synced`
        operacji w miejscu i bramka przyrostowa skanu (pisarz, który zachowuje `mtime`, jest poza
        nią); plik z nagłówkiem sprzed commitu (koperta: region bajt w bajt, tekst: hash) albo
        z nagłówkiem wyniku własnego → pod jedną blokadą dowód CAŁEGO pliku: kotwica koperty
        (`RegionBackup.file_sha1`) albo para odcisków śladu (wynik semantyczny, zmiana od commitu,
        backup tekstowy); baza opisuje plik → „już cofnięte”, nie → re-sync z tym samym dowodem; bez
        dowodu → 'blocked' z receptą skanu. Backup tekstowy bez śladu (cofnięty przed 0044) - jak
        dawniej, z uczciwym zdaniem, że reszty pliku nie da się sprawdzić. Backup tekstowy ZE śladem
        i plik, który nie jest wynikiem własnym (AR-229): dowodu nie będzie nigdy (brak kotwicy), więc
        po skanie, gdy baza opisuje cały plik (pełny sha1 pod blokadą == `location.file_sha1`) - to
        samo zdanie „reszty pliku nie da się sprawdzić”; przed skanem - 'blocked' z receptą skanu.

    PIERWSZE COFNIĘCIE ATOMOWE: ślad przed podmianą (porażka → 'failed', plik nietknięty), plik
    zmieniony poza nagłówkiem od commitu (`replace_intent.prepared_sha1` ≠ plik zastany) - cofnięcie
    idzie, powód to mówi; re-sync pod blokadą pliku wciąga WYŁĄCZNIE wynik własny (para śladu)
    albo plik sprzed commitu - zmiana w oknie między podmianą a odczytem → 'failed' bez re-syncu.

    PLIKI OBOK ŚCIEŻKI (AR-127, 0045): na końcu każdej próby ze śladem jej właściciel stawia werdykt
    kopii wypartej, zwrotnej i pliku tymczasowego (`clean` - nic nie zostało; `kept` - zostają do oka
    w Porządkach, dopisek do wyniku); ślad próby martwej albo cudzej rozstrzyga bramka przed następnym
    cofnięciem lub zapisem lokacji (`kept` + jednorazowa blokada). Żaden plik nie jest kasowany ani
    przenoszony.

    PRZERWANIE (`should_cancel`): `UndoResult.remaining` = ile nieprzetworzonych backupów NIE ma
    trwałego dowodu zakończenia (`_cofniecie_zakonczone`, bez odczytu plików, AR-176) - zdanie okna
    mówi „N wymaga sprawdzenia” albo „pozostałe nie wymagają cofnięcia”, bez obietnicy wyniku.

    „JUŻ COFNIĘTE” ROZLICZA BAZĘ (AR-169): przed uznaniem pliku za cofnięty skutki cofnięcia w bazie
    (nagrobek ręki AR-38, otwarte wstrzymanie commitu) rozlicza ta sama klinga co re-sync -
    idempotentnie, bez pliku (`_rozlicz_cofniecie_w_bazie`); inaczej skan po zewnętrznym powrocie
    pliku chowałby „Cofnij” bez odtworzenia wykluczenia.

    BRAMKA IZOLACJI: operacja izolująca lokację spoza tego commitu (`repo.isolating_inplace_op`) →
    'blocked' z drogą naprawy, zero zapisu - w obu drogach. Droga atomowa powtarza ją pod strażą
    podmiany (`repo.guard_file_replace`, jak w `commit`): zapis w miejscu zaczęty po bramce odbija
    `os.replace` zamiast zostać przez nie starty.

    COFNIĘCIE ODTWARZA WYKLUCZENIE (AR-38, decyzja Zdzinia): plik 'restored' wraca z nagrobkiem
    ręki, który commit zgasił kartą `OBJECT` na TYM pliku - w transakcji re-syncu (droga atomowa)
    albo dokończenia operacji cofnięcia (droga w miejscu, `repo.finish_inplace_op`). Plik
    'failed'/'blocked' nagrobka nie odtwarza. Commit sprzed AR-38 (zgaszenie bez `commit_id`)
    i klatka z nowszym werdyktem ręki → bez zmian (`repo._restore_object_tombstone_tx`)."""
    backups = backups_for_commit(con, commit_id)
    total = len(backups)
    restored: list[FileResult] = []
    blocked: list[FileResult] = []
    failed: list[FileResult] = []
    semantic: list[FileResult] = []
    withheld: list[FileResult] = []
    already: list[FileResult] = []
    kubly = {"restored": restored, "blocked": blocked, "failed": failed}
    cancelled = False
    remaining = None
    done = 0

    def _report(path, status):
        nonlocal done
        done += 1
        if progress is not None:
            progress(done, total, path, status)

    for i, b in enumerate(backups):
        if should_cancel is not None and should_cancel():
            cancelled = True
            remaining = sum(1 for r in backups[i:] if not _cofniecie_zakonczone(con, commit_id, r))
            break
        cofniecie = _cofnij_lokacje(con, commit_id, b, now=now)
        kubly[cofniecie.wynik.status].append(cofniecie.wynik)
        if cofniecie.semantycznie:
            semantic.append(cofniecie.wynik)
        if cofniecie.wstrzymane:
            withheld.append(cofniecie.wynik)
        if cofniecie.juz:                       # „już cofnięte” - nie ma czego ponawiać (AR-160)
            already.append(cofniecie.wynik)
        _report(cofniecie.wynik.path, cofniecie.wynik.status)

    return UndoResult(commit_id, restored, blocked, failed, cancelled, semantic=semantic,
                      withheld=withheld, already=already, remaining=remaining)


def _cofniecie_zakonczone(con, commit_id, b) -> bool:
    """Czy backup `b` commitu ma TRWAŁY DOWÓD, że cofania nie ma albo już się zakończyło - z bazy,
    bez odczytu pliku (AR-176): commit pliku nie podmienił (`unreplaced_at`) albo operacja cofnięcia
    w miejscu jest zamknięta (`undo` w `synced`). Zgodny `header_hash` lokacji tym dowodem NIE jest:
    skan po zewnętrznym powrocie pliku wyrównuje nagłówek, a cały plik i skutki cofnięcia w bazie
    (nagrobek AR-38, wstrzymania) mogą być inne - rozstrzyga dopiero cofnięcie tego backupu. Droga
    atomowa (AR-182): ślad własnego cofnięcia, który baza wciągnęła (`_wynik_wlasny_w_bazie`). Każdy
    inny backup wymaga sprawdzenia."""
    if con.execute("SELECT unreplaced_at FROM header_backups WHERE id = ?",
                   (b["id"],)).fetchone()[0] is not None:
        return True
    op_u = _ostatnia_operacja(con, commit_id, int(b["location_id"]), "undo")
    if op_u is not None and op_u["phase"] == "synced":
        return True
    return _wynik_wlasny_w_bazie(con, b) is not None


def _wynik_wlasny_w_bazie(con, b):
    """Ślad cofnięcia backupu `b` drogą atomową (`atomic_undo`, AR-182), który baza wciągnęła
    (`synced_at`) i którego para odcisków jest parą lokacji (`location.file_sha1`/`header_hash`) -
    ostatni pełny odczyt bazy to był ten wynik; najnowszy taki albo `None`. Bez odczytu pliku: JEDNA
    reguła dla dowodu zakończenia (`_cofniecie_zakonczone`) i szybkiej ścieżki „już cofnięte”
    (`_cofnij_lokacje`, która dokłada `mtime` pliku)."""
    return con.execute(
        "SELECT au.id, au.result_sha1, au.result_hash FROM atomic_undo au "
        "JOIN location l ON l.id = ? "
        "WHERE au.backup_id = ? AND au.synced_at IS NOT NULL "
        "AND au.result_sha1 = l.file_sha1 AND au.result_hash = l.header_hash "
        "ORDER BY au.id DESC LIMIT 1", (int(b["location_id"]), b["id"])).fetchone()


def _slad_pary(con, backup_id, sha1, naglowek):
    """Najnowszy ślad cofnięcia backupu z parą odcisków `(sha1, naglowek)` - bez względu na
    `synced_at` (AR-182): oznaczenie wciągnięcia dotyczy wyłącznie jego, a starsza próba z tym samym
    wynikiem (śmierć między śladem a podmianą, potem ponowienie) zostaje, jaka była. `None` = plik
    nie jest wynikiem żadnego cofnięcia tego backupu."""
    return con.execute(
        "SELECT max(id) FROM atomic_undo WHERE backup_id = ? AND result_sha1 = ? "
        "AND result_hash = ?", (backup_id, sha1, naglowek)).fetchone()[0]


# ------------------------------------------------ PLIKI OBOK ŚCIEŻKI PO COFNIĘCIU (AR-127, 0045)
# Cofnięcie drogą atomową może zostawić obok ścieżki trzy pliki: kopię wypartą K, kopię zwrotną Z
# (`_nazwa_zwrotna(K)`) i plik tymczasowy T - po śmierci procesu w oknie podmiany albo po awarii, którą
# powód nazywa (kopia nieusunięta, powrót wersji innego pisarza, który nie zaszedł). Ślad (0044) zna ich
# nazwy, a werdykt (0045) stawia je w wierszu Porządków „Kopie zostawione do oka”. Automat ich NIE
# kasuje i NIE przenosi: kasowanie wymagałoby dowodu, że plik jest bajtową kopią pliku, który zostaje,
# złożonego w chwili kasowania - to osobny wariant (rejestr), tu człowiek porównuje i usuwa zbędne.
#
# KTO PISZE WERDYKT. Trzy `stat` po kolei nie są jednym obrazem dysku: żywe cofnięcie innego procesu
# zamienia T w K (`ReplaceFileW`) i K w Z (powrót) między nimi, więc obserwator może zobaczyć „nie ma”
# trzy razy, choć w żadnej chwili wszystkich trzech nie brakowało, a ten proces zginie z K na dysku.
# Dlatego `clean` zapisuje WYŁĄCZNIE właściciel śladu - próba, która go utrwaliła, na końcu własnego
# cofnięcia, po własnym sprzątnięciu (`_werdykt_wlasciciela`). Obserwator (bramka `_rekoncyliuj_slady`
# przed cofnięciem i zapisem lokacji - ślad martwej albo cudzej próby) widzi plik → `kept`; widzi same
# „nie ma” albo „nie wiem” → ślad zostaje nierozstrzygnięty, bramka przepuszcza (kosztem trzech `stat`
# przy każdym dotyku, ok. 0,03 ms każdy na `R:`). Obserwator w wyścigu z żywym właścicielem może zapisać
# `kept` z nazwą, która za chwilę zniknie - zachowawczo: jedna odmowa, a wiersz Porządków sam znika, bo
# pokazuje wyłącznie nazwy, których brak nie jest dowiedziony. Straż podmiany (`repo.guard_file_replace`)
# obejmuje `ReplaceFileW` i powrót, ale nie okna śladu → straży i straży → usunięcia kopii, więc tej
# reguły nie zastępuje. Stan „nie wiem” (`scan.path_gone` → `None`: brak uprawnień, zerwany udział) nigdy
# nie jest brakiem.
#
# PRZEGLĄD (AR-231): ślady bez werdyktu, do których nikt nie wraca (lokacja bez kolejnego zapisu ani
# cofnięcia), przegląda `przejrzyj_slady_cofniecia` - TEN SAM obserwator co bramka (`_rozstrzygnij_slad`),
# więc też wyłącznie `kept`. Resztka martwej próby trafia do Porządków bez dotyku lokacji; ślad bez resztek
# zostaje bez werdyktu, bo `clean` z trzech `stat` obserwatora nie ma dowodu (nazwy K i T nie są
# rezerwowane - mogą wrócić w innej próbie).


def _nazwy_sladu(displaced_path: str, prepared_path: str) -> tuple[str, str, str]:
    """Nazwy plików, które ślad cofnięcia może zostawić obok ścieżki: K, Z, T - kolejność listy werdyktu
    (`atomic_undo.kept_paths`), nie kolejność powstawania (T powstaje pierwsze, jeszcze przed śladem)."""
    return displaced_path, _nazwa_zwrotna(displaced_path), prepared_path


def _rekoncyliuj_slady(con, loc, *, now) -> PowodPozycji | None:
    """BRAMKA ŚLADÓW COFNIĘCIA lokacji (AR-127) - OBSERWATOR, przed cofnięciem (`_cofnij_lokacje`)
    i zapisem karty (`_zapisz_lokacje`): ślady bez werdyktu (każdego commitu tej lokacji, od
    najstarszego) to próby martwe albo cudze. Któraś nazwa śladu JEST na dysku → `kept` z trzema
    nazwami (CAS; werdykt kanoniczny rozstrzyga powód) i jednorazowa blokada z powodem; same „nie ma”
    albo „nie wiem” → bez werdyktu i bez blokady (`clean` pisze wyłącznie właściciel - sekcja wyżej).
    Pliki NIGDY nie są ruszane. Porażka (baza, wyjątek odczytu) → powód z klasą błędu i blokada do
    ponowienia, ślad bez werdyktu. Zwraca pierwszy powód po przejściu wszystkich śladów albo `None`.
    Jeden ślad rozstrzyga `_rozstrzygnij_slad` - ten sam co przegląd (AR-231)."""
    powod = None
    for s in sorted(repo.unsettled_atomic_undos(con, loc["id"]), key=lambda r: r["id"]):
        werdykt = _rozstrzygnij_slad(con, s, now=now)
        if werdykt.wynik == "padl":
            powod = powod or werdykt.powod
        elif werdykt.wynik == "kept" and powod is None:
            powod = werdykt.powod
    return powod


@dataclasses.dataclass(frozen=True)
class _WerdyktSladu:
    """Rozstrzygnięcie JEDNEGO śladu przez obserwatora (`_rozstrzygnij_slad`): `wynik` = werdykt
    z WIERSZA KANONICZNEGO klingi (`kept`, `clean` - przegrany CAS bierze werdykt zwycięzcy), `bez_werdyktu`
    (trzy dowiedzione „nie ma”), `nie_wiem` (któreś „nie wiem”, żadne „jest” - stan dysku nieznany, ponowienie
    ma sens) albo `padl` (baza, wyjątek odczytu); `powod` - zdanie blokady bramki
    (`undo_cut_kept` przy kanonicznym `kept`, `undo_reconcile_failed` przy porażce) albo None; `nazwy` - przy
    `nie_wiem` nazwy z odczytem „nie wiem” (dla zdania Porządków)."""
    wynik: str
    powod: PowodPozycji | None = None
    nazwy: tuple = ()


def _rozstrzygnij_slad(con, s, *, now) -> _WerdyktSladu:
    """OBSERWATOR JEDNEGO ŚLADU (wiersz `repo.unsettled_atomic_undos`): któraś nazwa śladu JEST na dysku
    → `kept` z trzema nazwami (CAS), inaczej bez werdyktu (`clean` pisze wyłącznie właściciel - sekcja
    wyżej). Wspólny dla bramki lokacji (`_rekoncyliuj_slady`) i przeglądu (`przejrzyj_slady_cofniecia`)."""
    cid = s["commit_id"]
    nazwy = _nazwy_sladu(s["displaced_path"], s["prepared_path"])
    try:
        stan = {x: scan.path_gone(x) for x in nazwy}
        if not any(v is False for v in stan.values()):
            nie_wiem = tuple(x for x, v in stan.items() if v is None)
            return _WerdyktSladu("nie_wiem", nazwy=nie_wiem) if nie_wiem else _WerdyktSladu("bez_werdyktu")
        kanon = repo.settle_atomic_undo(con, undo_id=s["id"], outcome="kept", kept_paths=nazwy,
                                        now=now)
    except Exception as exc:  # noqa: BLE001 - raport zamiast wyjątku w warstwie zapisu
        blad = _blad_systemu(exc)
        return _WerdyktSladu("padl", PowodPozycji(
            f"rozstrzygnięcie plików obok ścieżki po cofnięciu commitu {cid} padło ({blad}) - "
            f"ponów operację", "undo_reconcile_failed", commit_id=cid, detail=blad))
    if kanon["outcome"] != "kept":
        return _WerdyktSladu(kanon["outcome"])
    widoczne = [x for x, v in stan.items() if v is not True]
    return _WerdyktSladu("kept", PowodPozycji(
        f"przerwane cofnięcie commitu {cid} zostawiło obok ścieżki pliki - zostają do oka "
        f"w Porządkach: {', '.join(widoczne)}", "undo_cut_kept", commit_id=cid, paths=widoczne))


@dataclasses.dataclass(frozen=True)
class PrzegladSladow:
    """Wynik przeglądu śladów cofnięcia bez werdyktu (`przejrzyj_slady_cofniecia`, AR-231): id śladów wg
    werdyktu z WIERSZA KANONICZNEGO - `kept` (obok ścieżki widziano plik: wiersz Porządków), `clean`
    (przegrany CAS - właściciel zdążył), `bez_werdyktu` (trzy dowiedzione „nie ma”), `nie_wiem` (stan dysku
    nieznany - `scan.path_gone` → `None`; ich nazwy z tym odczytem w `nie_wiem_nazwy`), `padly` (porażka bazy
    albo odczytu) - i powód pierwszej porażki albo None."""
    kept: tuple = ()
    clean: tuple = ()
    bez_werdyktu: tuple = ()
    nie_wiem: tuple = ()
    padly: tuple = ()
    powod: PowodPozycji | None = None
    nie_wiem_nazwy: tuple = ()


def przejrzyj_slady_cofniecia(con, *, now) -> PrzegladSladow:
    """PRZEGLĄD ŚLADÓW COFNIĘCIA bez werdyktu WSZYSTKICH lokacji (AR-231) - od najstarszego, ten sam
    obserwator co bramka (`_rozstrzygnij_slad`): resztka martwej próby dostaje `kept` i wiersz Porządków
    bez dotyku lokacji; ślad bez resztek zostaje bez werdyktu (`clean` wyłącznie właściciel). Porażka
    jednego śladu nie przerywa przeglądu. Pliki NIGDY nie są ruszane. Wyjątek odczytu listy śladów (baza)
    leci do wołającego."""
    wyniki = {"kept": [], "clean": [], "bez_werdyktu": [], "nie_wiem": [], "padl": []}
    powod, nie_wiem_nazwy = None, []
    for s in sorted(repo.unsettled_atomic_undos(con), key=lambda r: r["id"]):
        werdykt = _rozstrzygnij_slad(con, s, now=now)
        wyniki[werdykt.wynik].append(s["id"])
        nie_wiem_nazwy.extend(werdykt.nazwy)
        if werdykt.wynik == "padl" and powod is None:
            powod = werdykt.powod
    return PrzegladSladow(kept=tuple(wyniki["kept"]), clean=tuple(wyniki["clean"]),
                          bez_werdyktu=tuple(wyniki["bez_werdyktu"]), nie_wiem=tuple(wyniki["nie_wiem"]),
                          padly=tuple(wyniki["padl"]), powod=powod, nie_wiem_nazwy=tuple(nie_wiem_nazwy))


def _werdykt_wlasciciela(con, undo_id, nazwy, *, commit_id, now,
                         resync_potwierdzony) -> PowodPozycji | None:
    """WERDYKT WŁAŚCICIELA ŚLADU (AR-127): próba, która ślad utrwaliła, na końcu własnego cofnięcia -
    po własnym sprzątnięciu kopii wypartej i pliku tymczasowego (`write_full_header`). Wszystkie trzy
    nazwy „nie ma” → `clean` (jedyne miejsce, które go pisze) - ale WYŁĄCZNIE po potwierdzonym
    re-syncu tej próby (`resync_potwierdzony` - wynik 'restored'): po 'failed'/'blocked' ślad zostaje
    bez werdyktu (bramka przy następnym dotyku); któraś „jest” → `kept` z trzema nazwami (zawsze);
    któraś „nie wiem”, a żadna „jest” → bez werdyktu.

    Rozstrzyga WIERSZ KANONICZNY klingi, nie własna propozycja: przegrany CAS (obserwator zapisał
    `kept` między tą inwentaryzacją a zapisem `clean`) to `kept` - nazwy kanoniczne sprawdzane od
    nowa, bo obserwator widział plik, którego ta próba nie widziała. Zwraca dopisek do wyniku:
    obietnicę Porządków WYŁĄCZNIE przy kanonicznym `kept` i nazwie, której brak nie jest dowiedziony
    (zdanie nie może obiecać wiersza, którego czytelnik nie pokaże); przy stanie nieznanym albo
    porażce zapisu werdyktu - nazwy i receptę; `None`, gdy obok ścieżki nic nie zostało. Pliki
    nietknięte."""
    try:
        stan = {x: scan.path_gone(x) for x in nazwy}
        widoczne = [x for x, v in stan.items() if v is not True]
        if not widoczne:
            if not resync_potwierdzony:
                return None
            kanon = repo.settle_atomic_undo(con, undo_id=undo_id, outcome="clean", kept_paths=(),
                                            now=now)
        elif not any(v is False for v in stan.values()):
            return PowodPozycji(f"nie da się ustalić, czy obok ścieżki zostały pliki: "
                                f"{', '.join(widoczne)} - ponów cofnięcie albo sprawdź je ręcznie",
                                "undo_files_unknown", paths=widoczne)
        else:
            kanon = repo.settle_atomic_undo(con, undo_id=undo_id, outcome="kept", kept_paths=nazwy,
                                            now=now)
        if kanon["outcome"] != "kept":
            return None
        if not widoczne:                     # przegrany CAS: werdykt zwycięzcy, jego nazwy od nowa
            widoczne = [x for x in json.loads(kanon["kept_paths"]) if scan.path_gone(x) is not True]
    except Exception as exc:  # noqa: BLE001 - wynik cofnięcia już zapadł; ślad zostaje dla bramki
        blad = _blad_systemu(exc)
        return PowodPozycji(
            f"rozstrzygnięcie plików obok ścieżki po cofnięciu commitu {commit_id} padło ({blad}) - "
            f"ponów operację", "undo_reconcile_failed", commit_id=commit_id, detail=blad)
    if not widoczne:
        return None
    return PowodPozycji(f"pliki obok ścieżki zostają do oka w Porządkach („Kopie zostawione do oka”): "
                        f"{', '.join(widoczne)}", "undo_files_kept", paths=widoczne)


def _resync_padl(exc) -> PowodPozycji:
    """Powód cofnięcia, w którym nagłówek wrócił, a zapis bazy (re-sync albo rozliczenie skutków
    cofnięcia) padł - ponowienie dokończy samą synchronizację."""
    return _baza_po_przywroceniu_padla(_blad_systemu(exc))


def _baza_po_przywroceniu_padla(blad) -> PowodPozycji:
    """`_resync_padl` z gotowym błędem systemu klasą (`_blad_systemu`) - także dla blokady pliku pod
    re-sync, której wynik `_pod_blokada` oddaje już sklasyfikowany."""
    return PowodPozycji(f"nagłówek PRZYWRÓCONY, ale re-sync padł - {blad}; ponowne undo dokończy "
                        f"samą synchronizację", "undo_resync_failed", detail=blad)


def _rozlicz_cofniecie_w_bazie(con, commit_id, loc, *, now, slad=None) -> None:
    """Skutki cofnięcia commitu w bazie BEZ pliku - ta sama klinga co re-sync cofnięcia (`_sync`):
    otwarte wstrzymanie commitu na tej lokacji → `undone` (`repo.close_withheld_undone`) i nagrobek
    ręki zgaszony przez ten commit na tym pliku → odtworzony (`repo.restore_object_tombstone`, AR-38).
    Jedna transakcja; idempotentne (zamyka tylko otwarte, nagrobek raz na parę commit-plik, nowszy
    werdykt ręki wygrywa). Woła je każde „już cofnięte” (AR-169): skan po zewnętrznym powrocie pliku
    wyrównuje nagłówek, ale nagrobka nie odtwarza. `slad` = ślad cofnięcia (`atomic_undo.id`), którego
    wynik leży na dysku i w bazie - oznaczany w tej samej transakcji (AR-182)."""
    with repo.atomic(con):
        repo.close_withheld_undone(con, commit_id=commit_id, location_id=loc["id"], now=now)
        repo.restore_object_tombstone(con, frame_id=loc["frame_id"], commit_id=commit_id,
                                      location_id=loc["id"], now=now)
        if slad is not None:
            repo.mark_atomic_undo_synced(con, undo_id=slad, now=now)


def _baza_opisuje(loc, path, naglowek) -> bool:
    """Czy baza opisuje plik pod `path` z nagłówkiem `naglowek`: `location.header_hash` i `mtime`
    pliku na dysku - jedna reguła „już cofnięte” obu dróg cofnięcia (AR-169). Plik, którego nie da
    się zapytać o `mtime`, nie jest opisany."""
    try:
        mtime = scan._mtime_iso(os.stat(path))
    except OSError:
        return False
    return loc["header_hash"] == naglowek and loc["mtime"] == mtime


@dataclasses.dataclass(frozen=True)
class _CofniecieLokacji:
    """Wynik cofnięcia JEDNEGO backupu commitu. `semantycznie` - plik wrócił cofnięciem semantycznym
    (`UndoResult.semantic`). `juz` - stan sprzed commitu już leży na dysku i w bazie ('blocked' „już
    cofnięte” albo commit, który tego pliku nie podmienił): nie ma czego cofać, a ponowienie
    cofnięcia zmiany obiektu wolno uznać za domknięte. `wstrzymane` - nagłówek wrócił, zeznanie
    klatki nie (AR-82, `UndoResult.withheld`)."""
    wynik: FileResult
    semantycznie: bool = False
    juz: bool = False
    wstrzymane: bool = False


def _cofnij_lokacje(con, commit_id, b, *, now) -> _CofniecieLokacji:
    """CIAŁO `undo` DLA JEDNEGO BACKUPU commitu - wspólne dla `undo` i cofnięcia zmiany obiektu
    (`undo_object_change`: karta per pozycja, przed powrotem pliku). Drogi, bramki i statusy - opis
    `undo`."""
    def _sync(loc, path, expect, powod, semantycznie=False, kontrola=None, odmowa=_bez_dowodu,
              slad=None):
        """Re-sync drogi atomowej (bez operacji w dzienniku) - w jego transakcji odtworzenie
        nagrobka zgaszonego przez ten commit na tym pliku (AR-38). `semantycznie` - plik wrócił
        cofnięciem semantycznym (AR-19), wynik trafia też do `semantic`.

        `kontrola` (region w miejscu już sprzed commitu, AR-169; plik sprzed commitu albo wynik
        własny drogi atomowej, AR-182): ten sam pełny odczyt re-syncu dowodzi CAŁEGO pliku
        (`_kontrola_danych`); bez dowodu nic nie wjeżdża, a wynik to blokada z receptą skanu
        (`odmowa`), nie błąd - albo, przy `odmowa=None` (re-sync zaraz po podmianie: plik JEST
        zmieniony, baza nie), 'failed' z werdyktem kontroli.

        ŚLAD (AR-182): w transakcji re-syncu wciągnięty wynik własny dostaje `synced_at` - ślad
        `slad` (przebieg, który go utrwalił), gdy to on leży w bazie, a bez `slad` najnowszy ślad
        z parą odcisków wciągniętej lokacji (ponowienie).

        ZEZNANIE (AR-82): OTWARTE wstrzymanie cofanego commitu zamyka się jako `undone` przed
        wjazdem rekordu, a cofnięcie, którego nagłówka zeznanie nie przyjęło, zakłada wstrzymanie
        cofnięcia - chyba że TO cofnięcie zamknęło otwarte wstrzymanie commitu (zeznanie nigdy go
        nie przyjęło, więc nie ma czego cofać). Rozliczona historia wstrzymań (`completed`,
        `superseded`) tego nie znaczy: zeznanie przyjęło zapis, a teraz nie przyjęło powrotu (B2)."""
        wstrzymanie: list[str] = []
        zamkniete: list[bool] = []

        def _przed():
            zamkniete.append(repo.close_withheld_undone(con, commit_id=commit_id,
                                                        location_id=loc["id"], now=now))

        def _nagrobek(zeznanie):
            repo.restore_object_tombstone(con, frame_id=loc["frame_id"], commit_id=commit_id,
                                          location_id=loc["id"], now=now)
            sha1, naglowek = con.execute("SELECT file_sha1, header_hash FROM location WHERE id = ?",
                                         (loc["id"],)).fetchone()
            pasujacy = _slad_pary(con, b["id"], sha1, naglowek)
            if pasujacy is not None and slad in (None, pasujacy):
                repo.mark_atomic_undo_synced(con, undo_id=pasujacy, now=now)
            if zeznanie or zamkniete[0]:
                return
            powod_w = repo.withheld_reason(con, location_id=loc["id"], commit_id=commit_id,
                                           undo=True)
            repo.withhold_write(con, kind="undo", location_id=loc["id"], commit_id=commit_id,
                                header_hash=naglowek, reason=powod_w, now=now)
            wstrzymanie.append(powod_w)
        try:
            wynik = _resync(con, path, loc["volume"], now=now, expect_sha1_data=expect,
                            kontrola=kontrola, przed_wciagnieciem=_przed, w_transakcji=_nagrobek)
            if kontrola is not None and wynik.niezgodne is not None and odmowa is not None:
                return _blok(loc, path, odmowa(wynik.niezgodne))
            niezgodne = wynik.niezgodne
        except Exception as exc:  # noqa: BLE001 - nagłówek przywrócony, pętla idzie dalej
            niezgodne = _resync_padl(exc)
        if niezgodne is not None:
            return _pad(loc, path, niezgodne)
        if wstrzymanie:
            return _CofniecieLokacji(
                FileResult(loc["id"], path, "restored", _dopisz(powod, wstrzymanie[0]),
                           code=CODE_ZEZNANIE_WSTRZYMANE),
                semantycznie=semantycznie, wstrzymane=True)
        return _CofniecieLokacji(FileResult(loc["id"], path, "restored", powod),
                                 semantycznie=semantycznie)

    def _dokoncz_undo(loc, path, op_id, powod):
        """Dokończenie operacji cofnięcia w miejscu (`_dokoncz`) z wynikiem undo."""
        wynik = _dokoncz(con, op_id, now=now)
        if wynik.status == "applied" and wynik.code == CODE_ZEZNANIE_WSTRZYMANE:
            return _CofniecieLokacji(FileResult(loc["id"], path, "restored",
                                                _dopisz(powod, wynik.reason),
                                                code=CODE_ZEZNANIE_WSTRZYMANE), wstrzymane=True)
        if wynik.status == "applied":
            return _CofniecieLokacji(FileResult(loc["id"], path, "restored", powod))
        if wynik.status == "blocked":
            return _blok(loc, path, PowodPozycji(f"{wynik.reason}; lokacja IZOLOWANA od skanu",
                                                 "isolated_suffix", inner=wynik.reason))
        return _pad(loc, path, PowodPozycji(
            f"nagłówek PRZYWRÓCONY, ale {wynik.reason}; lokacja IZOLOWANA od skanu - ponowne undo "
            f"dokończy samą synchronizację", "undo_finish_failed", inner=wynik.reason))

    def _blok(loc, path, powod, juz=False, slad=None):
        if juz:
            # „Już cofnięte” rozlicza skutki cofnięcia w bazie - JEDNA reguła każdej drogi (AR-169);
            # wynik własny drogi atomowej dostaje przy tym `synced_at` swojego śladu (AR-182).
            try:
                _rozlicz_cofniecie_w_bazie(con, commit_id, loc, now=now, slad=slad)
            except Exception as exc:  # noqa: BLE001 - plik cofnięty, baza do ponowienia
                return _pad(loc, path, _resync_padl(exc))
        return _CofniecieLokacji(FileResult(loc["id"], path, "blocked", powod), juz=juz)

    def _pad(loc, path, powod):
        return _CofniecieLokacji(FileResult(loc["id"], path, "failed", powod))

    def _kontrola(env, op_c, naglowek, wlasne):
        """Kontrola całego pliku cofnięcia: region i kotwica sprzed commitu z koperty (kotwica
        operacji commitu w miejscu, a dla operacji sprzed 0023 i commitu atomowego - `file_sha1`
        koperty; nigdy mutowalne `location.file_sha1`) i pary odcisków wyników własnych (AR-182).
        Backup tekstowy - bez regionu i bez kotwicy: dowodem jest wyłącznie wynik własny."""
        if env is None:
            return _KontrolaDanych(0, None, None, naglowek, wlasne)
        kotwica = (op_c["anchor_sha1"] if op_c is not None else None) or env.file_sha1
        return _KontrolaDanych(env.offset, env.region, kotwica, naglowek, wlasne)

    def _region_sprzed(loc, path, env, op_c, wlasne=frozenset(), naglowek=None, tekst=False):
        """AR-169: region nagłówka na dysku już równy stanowi sprzed commitu (w miejscu: powrót spoza
        Horreum; atomowo, AR-182: także wynik własnego cofnięcia). „Już cofnięte” i re-sync wymagają
        dowodu CAŁEGO pliku - pod jedną blokadą, tą samą kontrolą danych, którą zapis w miejscu
        chroni bajty poza regionem: plik z podstawionym regionem backupu (tu: bieżącym) ma sha1
        kotwicy sprzed commitu (`_kontrola`), nagłówek = `pre_hash`, `sha1_data` klatki - albo para
        odcisków pliku jest parą śladu własnego cofnięcia (`wlasne`). Baza opisuje ten plik → „już
        cofnięte” (`juz`); baza nie → re-sync z tym samym dowodem (nagrobek AR-38 i wstrzymania jak
        w drodze atomowej); bez dowodu → blokada z receptą skanu, uchwyt „Cofnij” zostaje (drugie
        HDU albo dane zmienione obok regionu).

        `naglowek` = plik rozpoznany NAGŁÓWKIEM, nie bajtami regionu koperty (backup tekstowy,
        nagłówek wyniku własnego z innymi bajtami regionu): bez porównania regionu pod blokadą,
        a odmowa mówi o wyniku własnym (`_bez_dowodu_wlasnego`), nie o regionie.

        BACKUP TEKSTOWY PRZYJĘTY SKANEM (AR-229, `tekst` - backup bez koperty, plik z nagłówkiem
        SAMEGO backupu): kotwicy całego pliku nie ma, więc dowodu nie będzie nigdy, a odmowa
        `check_no_anchor` szłaby w kółko także po skanie, o który prosi. Domyka ją „baza opisuje
        plik” w ścisłym sensie - pod tą blokadą, w tym samym pełnym odczycie: `_baza_opisuje`
        (nagłówek i `mtime`), kontrola danych odmawia WYŁĄCZNIE z braku kotwicy (`sha1_data` klatki,
        nagłówek backupu i „nie wynik własny” już sprawdzone) ORAZ pełny sha1 pliku ==
        `location.file_sha1`. Ten odcisk stawia wyłącznie pełny odczyt bazy: nowa kopia
        (`repo.add_location`, `repo.py:370`) albo wjazd rekordu znanej ścieżki (`repo.refresh_location`,
        `repo.py:1169`, wołane przez `scan.ingest_record` - każdy skan i każdy re-sync pisarza,
        `_resync`). Po commicie niósł wynik commitu (jego re-sync; gdy ten padł - odcisk sprzed
        commitu), a po własnym cofnięciu - wynik ze śladu (para w `wlasne`, gałąź wyżej), więc równość
        z plikiem, który nie jest wynikiem własnym, a ma nagłówek sprzed commitu, znaczy: baza zna
        dokładnie te bajty z pełnego odczytu - skanu po commicie (gest człowieka po odmowie), re-syncu
        późniejszej operacji tej lokacji albo odczytu sprzed commitu, jeśli jego re-sync padł; w każdym
        z tych wypadków baza i plik opisują stan sprzed commitu. Bajty zmienione po tym odczycie mają
        inny sha1 - także przy zachowanym `mtime` - i dostają odmowę. Zdanie (`_JUZ_TEKST`) mówi
        granicę: reszty pliku backup tekstowy nie pozwala sprawdzić. Bez opisu bazy - odmowa jak
        dotąd (re-sync niżej nie wciąga pliku bez dowodu; automatyczne „już cofnięte” bez skanu nie
        wraca)."""
        po_naglowku = naglowek is not None
        kontrola = _kontrola(env, op_c, naglowek if po_naglowku else env.pre_hash, wlasne)
        odmowa = _bez_dowodu_wlasnego if po_naglowku else _bez_dowodu

        def _dzialanie(fh):
            if not po_naglowku:
                fh.seek(env.offset)
                if fh.read(len(env.region)) != env.region:      # zmiana między blokadami
                    return _blok(loc, path, _REGION_ZMIENIONY)
            if _baza_opisuje(loc, path, kontrola.header_hash):
                rec = _skan_kontrolny(path, kontrola)
                niezgodne = _kontrola_danych(rec, loc["sha1_data"], kontrola)
                if (tekst and getattr(niezgodne, "code", None) == "check_no_anchor"
                        and rec.file_sha1 == loc["file_sha1"]):
                    return _blok(loc, path, _JUZ_TEKST, juz=True)
                if niezgodne is not None:
                    return _blok(loc, path, odmowa(niezgodne))
                if (rec.file_sha1, rec.header_hash) in wlasne:
                    return _blok(loc, path, _JUZ_WLASNE, juz=True,
                                 slad=_slad_pary(con, b["id"], rec.file_sha1, rec.header_hash))
                return _blok(loc, path, _JUZ_REGION if op_c is not None else _JUZ_ATOMOWO,
                             juz=True)
            return _sync(loc, path, loc["sha1_data"], _UNDO_DOKONCZONA_SYNCHRONIZACJA,
                         kontrola=kontrola, odmowa=odmowa)
        wynik = _pod_blokada(path, _dzialanie)
        if isinstance(wynik, WriteResult):                  # blokada nie powstała / wyjątek
            return _pad(loc, path, wynik.reason)
        return wynik

    loc = _location(con, int(b["location_id"]))
    if loc is None:
        return _CofniecieLokacji(FileResult(int(b["location_id"]), "", "failed", _BRAK_LOCATION))
    path = loc["path"]
    # Zwykłe cofnięcie tylko dla podmian potwierdzonych (AR-40): backup niepotwierdzony tej
    # lokacji (dowolnego commitu) rozstrzyga najpierw dysk.
    zalegle = repo.pending_header_backups(con, loc["id"])
    if zalegle:
        powod = _rekoncyliuj_backupy(con, zalegle, loc, now=now)
        if powod is not None:
            return _blok(loc, path, powod)
        loc = _location(con, loc["id"])
        if con.execute("SELECT unreplaced_at FROM header_backups WHERE id = ?",
                       (b["id"],)).fetchone()[0] is not None:
            return _blok(loc, path, PowodPozycji(
                "rekoncyliacja z dyskiem: commit nie podmienił tego pliku (na dysku nagłówek sprzed "
                "commitu) - nie ma czego cofać", "undo_not_replaced"), juz=True)
    # BRAMKA ŚLADÓW COFNIĘCIA (AR-127): pliki zostawione obok ścieżki przez przerwane cofnięcie tej
    # lokacji (dowolnego commitu) dostają werdykt `kept` i wiersz Porządków - raz, przed tym cofnięciem.
    powod = _rekoncyliuj_slady(con, loc, now=now)
    if powod is not None:
        return _blok(loc, path, powod)
    op_c = _ostatnia_operacja(con, commit_id, loc["id"], "commit")
    op_u = _ostatnia_operacja(con, commit_id, loc["id"], "undo")
    otwarta = next((o for o in (op_u, op_c)
                    if o is not None and o["phase"] in repo.INPLACE_OPEN_PHASES), None)
    if otwarta is not None:
        return _pad(loc, path, PowodPozycji(
            f"przerwany zapis w miejscu (operacja {otwarta['id']}, {otwarta['kind']}) - lokacja "
            f"izolowana; najpierw {_droga_przywroc(otwarta['id'])}", "undo_open_op",
            op_id=otwarta["id"], op_kind=otwarta["kind"], way=_droga_przywroc(otwarta["id"])))
    if op_u is not None and op_u["phase"] == "written":
        return _dokoncz_undo(loc, path, op_u["id"], _UNDO_DOKONCZONA_SYNCHRONIZACJA)
    if op_u is not None and op_u["phase"] == "synced":
        return _blok(loc, path, PowodPozycji("już cofnięte (operacja cofnięcia zamknięta)",
                                             "undo_already_op"), juz=True)
    if op_c is not None and op_c["phase"] == "written":
        # Commit zapisał i zweryfikował plik, ale jego re-sync padł (lokacja izolowana). Cofamy
        # dopiero stan, który baza zna: najpierw dokończenie commitu, potem zwykłe cofnięcie.
        koniec = _dokoncz(con, op_c["id"], now=now)
        if koniec.status != "applied":
            return (_pad if koniec.status == "failed" else _blok)(loc, path, PowodPozycji(
                f"commit nie jest dokończony (operacja {op_c['id']}): {koniec.reason}; lokacja "
                f"IZOLOWANA od skanu", "undo_commit_unfinished", op_id=op_c["id"],
                inner=koniec.reason))
        op_c = _ostatnia_operacja(con, commit_id, loc["id"], "commit")
        loc = _location(con, loc["id"])         # kotwica i mtime po dokończeniu commitu
    gen = repo.inplace_generation(con)          # przed bramką - dla straży podmiany atomowej
    izolujaca = repo.isolating_inplace_op(con, loc["id"])
    if izolujaca is not None:                   # nieukończony zapis spoza tego commitu
        return _blok(loc, path, _powod_izolacji(izolujaca))
    try:
        env = RegionBackup.decode(b["header_text"])
    except ValueError as exc:
        blad = _blad_systemu(exc, z_typem=False)
        return _pad(loc, path, PowodPozycji(f"uszkodzona koperta backupu: {blad}",
                                            "backup_envelope_broken", detail=blad))
    # Ślady własnych cofnięć tego backupu drogą atomową (0044, AR-182) - pary odcisków wyników.
    slady = repo.atomic_undos(con, b["id"])
    wlasne = frozenset((s["result_sha1"], s["result_hash"]) for s in slady)

    if env is not None and op_c is not None and op_c["phase"] == "synced":
        class _Dziennik:
            op_id = None

            def begin(self, spec, backup_text):
                self.op_id = repo.begin_inplace_undo(con, commit_id=commit_id,
                                                     location_id=loc["id"], spec=spec, now=now)

            def phase(self, faza, reason=None):
                repo.set_inplace_op_phase(con, op_id=self.op_id, phase=faza, now=now,
                                          reason=reason, expect_phase="writing")
        dziennik = _Dziennik()
        spec_c = _spec_z_operacji(op_c)
        res = restore_inplace(path, env, op_new_region=spec_c.new_region,
                              op_file_size=spec_c.file_size, op_file_ino=spec_c.file_ino,
                              op_post_hash=spec_c.post_hash, journal=dziennik,
                              anchor=FileAnchor(loc["file_sha1"], loc["mtime"]))
        if not isinstance(res, Fallback):
            if res.status == "applied":
                return _dokoncz_undo(loc, path, dziennik.op_id, None)
            if res.code == CODE_REGION_SPRZED:
                return _region_sprzed(loc, path, env, op_c, wlasne)
            if res.status == "blocked":
                return _blok(loc, path, res.reason)
            if not res.in_place:
                return _pad(loc, path, res.reason)
            return _pad(loc, path, PowodPozycji(
                f"{res.reason}; lokacja IZOLOWANA od skanu, odzysk: "
                f"{_droga_przywroc(dziennik.op_id)}", "undo_partial_isolated", inner=res.reason,
                way=_droga_przywroc(dziennik.op_id)))

    # Droga atomowa. SZYBKA ŚCIEŻKA (AR-182): baza wciągnęła wynik własnego cofnięcia (para odcisków
    # lokacji = para śladu z `synced_at`), a `mtime` pliku jest tym z bazy → „już cofnięte” bez
    # odczytu pliku. Granica zaufania jak faza `synced` operacji w miejscu i bramka przyrostowa
    # skanu: pisarz, który zmienia plik z zachowanym `mtime`, jest poza nią; zmiana z nowym `mtime`
    # (także wciągnięta skanem - inna para lokacji) idzie niżej, do dowodu całego pliku.
    domkniety = _wynik_wlasny_w_bazie(con, b)
    if domkniety is not None and _baza_opisuje(loc, path, domkniety["result_hash"]):
        return _blok(loc, path, _JUZ_WLASNE, juz=True)
    # Rozpoznanie „już przywrócone” z pliku: koperta - bajty regionu sprzed commitu, backup
    # tekstowy - nagłówek; plik z nagłówkiem wyniku własnego (droga semantyczna z innymi bajtami
    # regionu) też idzie do dowodu całego pliku.
    naglowek = None
    tekst = False                     # backup tekstowy, plik z nagłówkiem samego backupu (AR-229)
    try:
        if env is not None:
            with open(path, "rb") as fh:
                fh.seek(env.offset)
                na_miejscu = fh.read(len(env.region)) == env.region
        else:
            naglowek = _post_hash(path)
            na_miejscu = tekst = naglowek == _backup_pre_hash(path, b["header_text"])
        if not na_miejscu and slady:
            naglowek = naglowek or _post_hash(path)
            na_miejscu = naglowek in {s["result_hash"] for s in slady}
    except Exception:  # noqa: BLE001 - rozpoznanie tylko pomaga; decyduje pisarz niżej
        na_miejscu = False
    if na_miejscu:
        if env is None and not slady:
            # Backup tekstowy cofnięty przed 0044: bez kotwicy i bez śladu - jak dawniej, ale zdanie
            # mówi, czego nie sprawdzono.
            if _baza_opisuje(loc, path, naglowek):
                return _blok(loc, path, _JUZ_TEKST, juz=True)
            return _sync(loc, path, loc["sha1_data"], _UNDO_DOKONCZONA_SYNCHRONIZACJA)
        # Region sprzed commitu (każda droga commitu, AR-169/AR-182) albo nagłówek wyniku własnego -
        # wyłącznie z dowodem CAŁEGO pliku; inaczej podmieniona kopia z innym drugim HDU byłaby
        # „już cofnięta”. Backup tekstowy ze śladem bez dowodu domyka skan (AR-229, `tekst`).
        return _region_sprzed(loc, path, env, op_c, wlasne, naglowek, tekst=tekst)
    zamiar = repo.replace_intent(con, b["id"])
    utrwalony: list[tuple[int, str, str]] = []
    nazwy_proby: list[tuple[str, str, str]] = []      # K, Z, T tej próby (AR-127)

    def _utrwal(w):
        utrwalony.append((repo.record_atomic_undo(
            con, backup_id=b["id"], result_sha1=w.result_sha1, result_size=w.result_size,
            result_hash=w.result_hash, byte_exact=w.byte_exact, source_sha1=w.source_sha1,
            source_size=w.source_size, displaced_path=w.displaced_path,
            prepared_path=w.prepared_path, now=now), w.result_sha1, w.result_hash))
        nazwy_proby.append(_nazwy_sladu(w.displaced_path, w.prepared_path))
    res = write_full_header(
        path, b["header_text"], b["post_hash"],
        replace_guard=lambda: repo.guard_file_replace(con, location_id=loc["id"], generation=gen),
        persist_result=_utrwal,
        expect_file_sha1=(zamiar["prepared_sha1"] if zamiar is not None
                          and zamiar["outcome"] == "replaced" else None))

    def _po_zapisie():
        if res.status == "applied":
            # Kontrola tożsamości jak w commicie i w gałęzi „już przywrócone": astropy zapisuje cały
            # `HDUList`, więc inna serializacja sekcji danych dałaby nowe `sha1_data`, a re-sync bez
            # kotwicy przepiąłby lokację na nową klatkę, zostawiając fakty ręki na starej. Powód
            # niesie prawdę o bajtach (AR-19): `None` = cały plik jak przed commitem. Re-sync pod
            # blokadą pliku (jak `_region_sprzed`) wciąga WYŁĄCZNIE wynik tego cofnięcia (para śladu)
            # albo plik sprzed commitu (kotwica) - zmiana w oknie po podmianie → 'failed' (AR-182).
            if not utrwalony:
                raise AssertionError("cofnięcie podmieniło plik bez śladu wyniku - błąd pisarza")
            slad, sha1, naglowek_wyniku = utrwalony[0]
            kontrola = _kontrola(env, op_c, res.post_hash, wlasne | {(sha1, naglowek_wyniku)})
            wynik = _pod_blokada(path, lambda fh: _sync(
                loc, path, loc["sha1_data"], res.reason, semantycznie=res.byte_exact is False,
                kontrola=kontrola, odmowa=None, slad=slad))
            if isinstance(wynik, WriteResult):          # blokada pod re-sync nie powstała
                return _pad(loc, path, _baza_po_przywroceniu_padla(wynik.reason))
            return wynik
        if res.status == "blocked":
            return _blok(loc, path, res.reason)
        if res.backup_text is not None:
            # Podmiana zaszła, weryfikacja po niej nie (AR-8): re-syncu NIE ma - baza opisuje bajty
            # potwierdzone, jak po 'failed' commitu. Drogą naprawy jest skan albo ponowne undo,
            # które rozpozna przywrócony nagłówek po bajtach regionu.
            return _pad(loc, path, PowodPozycji(
                f"{res.reason}; baza NIE zsynchronizowana - przeskanuj plik albo ponów cofnięcie",
                "undo_not_synced", inner=res.reason))
        return _pad(loc, path, res.reason)
    wynik = _po_zapisie()
    if not utrwalony:
        return wynik
    # WŁAŚCICIEL ŚLADU (AR-127): ta próba skończyła swoje sprzątanie (kopia wyparta, plik tymczasowy) -
    # werdykt plików obok ścieżki zapada teraz (`clean` tylko po potwierdzonym re-syncu); dopisek
    # (obietnica Porządków albo uczciwa recepta) wyłącznie z werdyktu kanonicznego.
    dopisek = _werdykt_wlasciciela(con, utrwalony[0][0], nazwy_proby[0], commit_id=commit_id,
                                   now=now, resync_potwierdzony=wynik.wynik.status == "restored")
    if dopisek is None:
        return wynik
    return dataclasses.replace(wynik, wynik=dataclasses.replace(
        wynik.wynik, reason=_dopisz(wynik.wynik.reason, dopisek)))


_UNDO_DOKONCZONA_SYNCHRONIZACJA = PowodPozycji(
    "nagłówek był już przywrócony - dokończono synchronizację bazy", "undo_sync_finished")


def recover_torn(con, op_id, *, now) -> FileResult:
    """ODZYSK ROZDARTEGO NAGŁÓWKA po operacji `inplace_op.id` (astra Z11): tylko operacja OTWARTA
    (`writing`/`unverified`), tylko gdy region pliku pod blokadą jest jej stanem pośrednim
    (`_odzysk_pod_blokada`). Zwraca `FileResult` ('restored' | 'blocked' | 'failed').

    CAŁOŚĆ POD JEDNĄ BLOKADĄ PLIKU (astra, 2026-09-27): faza operacji czytana OD NOWA pod blokadą
    i brak późniejszej operacji tej lokacji - spóźnione drugie wywołanie, które widziało operację
    otwartą przed blokadą, nie cofnie nowszego, poprawnego zapisu (poprawny ponowny commit tej samej
    wartości zostawia region, który jest „stanem pośrednim" starej operacji). Po przywróceniu
    regionu re-sync z kontrolą danych (`sha1_data`, nagłówek sprzed operacji, sha1 całego pliku ==
    kotwica sprzed zapisu) i dopiero wtedy CAS fazy → `recovered`. Wyjątek re-syncu (czkawka
    odczytu) albo porażka fazy zostawia operację OTWARTĄ (izolacja trwa), a ponowienie jest
    bezpieczne: region stary jest też stanem pośrednim, więc drugi odzysk nic nie pisze i powtarza
    samą kontrolę z re-synciem.

    KONTROLA DANYCH, KTÓRA NIE PRZECHODZI, nie jest czkawką (AR-17 (6)): ponowienie powtórzyłoby tę
    samą niezgodność, a jedynym wyjściem zostawało ręczne zwolnienie izolacji. Idzie więc tą samą
    drogą powrotu co faza `written` (`_zwolnij_do_skanu`, CAS fazy przeczytanej pod blokadą): stary
    nagłówek już stoi w miejscu, faza `recovered` z powodem, wpisy stagingu 'failed',
    `location.mtime` → NULL, a pełny skan opisze plik razem z tym, co zmieniło się poza nagłówkiem.

    OPERACJA `written` → DROGA POWROTU (`_powrot_z_written`, astra 2026-09-27): wyłącznie wtedy,
    gdy kontrola danych tej operacji NIE przechodzi. Inaczej lokacja stałaby zablokowana bez drogi
    wyjścia: dokończenie powtarza tę samą niezgodność, undo wymaga dokończenia, a skan izolowaną
    pomija."""
    op = con.execute("SELECT * FROM inplace_op WHERE id = ?", (op_id,)).fetchone()
    if op is None:
        return FileResult(0, "", "failed", _brak_operacji(op_id))
    loc = _location(con, int(op["location_id"]))
    if loc is None:
        return FileResult(int(op["location_id"]), "", "failed", _BRAK_LOCATION)
    path = loc["path"]
    if op["phase"] == "written":
        return _powrot_z_written(con, op, loc, now=now)
    if op["phase"] not in repo.INPLACE_OPEN_PHASES:
        return FileResult(loc["id"], path, "blocked", PowodPozycji(
            f"operacja {op_id} nie jest otwarta ({op['phase']}) - odzysk dotyczy wyłącznie "
            f"przerwanego zapisu", "recover_not_open", op_id=op_id, phase=op["phase"]))
    spec = _spec_z_operacji(op)
    kontrola = _KontrolaDanych(spec.region_offset, spec.old_region,
                               _kotwica_operacji(con, op, loc), spec.pre_hash)

    def _dzialanie(fh):
        faza = repo.inplace_op_phase(con, op_id)
        if faza not in repo.INPLACE_OPEN_PHASES:
            return WriteResult("blocked", PowodPozycji(
                f"operacja {op_id} przestała być otwarta ({faza}) - odzysk odmawia",
                "recover_closed_meanwhile", op_id=op_id, phase=faza), None)
        if repo.newer_inplace_op(con, location_id=loc["id"], op_id=op_id):
            return WriteResult("blocked", PowodPozycji(
                f"lokacja ma operację nowszą niż {op_id} - odzysk odmawia, żeby nie cofnąć "
                f"późniejszego zapisu", "recover_newer_op", op_id=op_id), None)
        res = _odzysk_pod_blokada(fh, path, spec)
        if res.status != "applied":
            return res
        ponow = PowodPozycji(f"operacja zostaje otwarta, ponów {_droga_przywroc(op_id)}",
                             "way_retry_open", way=_droga_przywroc(op_id))
        try:
            niezgodne = _resync(con, path, loc["volume"], now=now,
                                expect_sha1_data=loc["sha1_data"], kontrola=kontrola).niezgodne
        except Exception as exc:  # noqa: BLE001 - czkawka odczytu nie jest werdyktem
            blad = _blad_systemu(exc)
            return WriteResult("failed", PowodPozycji(
                f"region przywrócony, ale re-sync padł - {blad}; {ponow}", "recover_resync_failed",
                detail=blad, way=ponow), None)
        if niezgodne is not None:          # werdykt kontroli danych - droga powrotu, nie ponowienie
            return _zwolnij_do_skanu(con, op_id, faza, niezgodne, now=now, ponow=ponow)
        try:
            repo.set_inplace_op_phase(con, op_id=op_id, phase="recovered", now=now,
                                      reason="region stary przywrócony (recover_torn)",
                                      expect_phase=faza)
        except Exception as exc:  # noqa: BLE001
            blad = _blad_systemu(exc)
            return WriteResult("failed", PowodPozycji(
                f"region przywrócony i baza zsynchronizowana, ale faza 'recovered' NIE zapisana "
                f"({blad}); {ponow}", "recover_phase_not_saved", detail=blad, way=ponow), None)
        return res
    wynik = _pod_blokada(path, _dzialanie)
    status = "restored" if wynik.status == "applied" else wynik.status
    return FileResult(loc["id"], path, status, wynik.reason)


def _powrot_z_written(con, op, loc, *, now) -> FileResult:
    """DROGA POWROTU z fazy `written` z NIEUDANĄ kontrolą danych (astra, 2026-09-27) - wszystko pod
    jedną blokadą pliku:

      1. faza czytana od nowa (`written`), brak nowszej operacji lokacji, ten sam plik (rozmiar,
         `st_ino`), region nagłówka = wynik operacji albo jej stan pośredni (przerwany wcześniejszy
         powrót); każdy inny region → 'blocked', instrukcja ręczna;
      2. region = wynik operacji → kontrola danych OD NOWA (`_kontrola_danych`: `sha1_data`,
         nagłówek zapisany przez operację, plik z podstawionym starym regionem == kotwica operacji).
         Kontrola PRZECHODZI → 'blocked': zapis jest poprawny, powrót go nie cofnie - drogą jest
         `finish_inplace`. Odczyt kontrolny padł → 'failed', ponowienie;
      3. stary region wraca w miejscu tą samą klingą co odzysk (`_odzysk_pod_blokada`: zapis tylko
         w zakresie operacji, weryfikacja nagłówka == `pre_hash`). Plik wraca do stanu sprzed
         zapisu RAZEM z tym, co zmieniło się poza nagłówkiem - tego powrót nie ukrywa i nie naprawia;
      4. JEDNA transakcja (`repo.revert_inplace_op`): faza `recovered` z powodem, wpisy stagingu
         operacji 'failed' z tym samym powodem i `location.mtime` → NULL - lokacja wraca do skanu,
         a brama przyrostowa jej nie pominie (pełny odczyt opisze plik od nowa).

    Re-syncu tu NIE MA: kontrola danych nie przeszła, więc baza nie ma kotwicy, wobec której
    wciągnięcie pliku byłoby dowodem - robi to pełny skan. Przerwa po kroku 3 zostawia `written`
    z regionem starym (stan pośredni), a ponowienie przechodzi od razu do kroku 4. Zwraca
    `FileResult` ('restored' | 'blocked' | 'failed')."""
    op_id, path = op["id"], loc["path"]
    spec = _spec_z_operacji(op)
    kontrola = _KontrolaDanych(spec.region_offset, spec.old_region,
                               _kotwica_operacji(con, op, loc), spec.post_hash)
    ponow = PowodPozycji(f"operacja zostaje 'written', ponów {_droga_przywroc(op_id)}",
                         "way_retry_written", way=_droga_przywroc(op_id))

    def _dzialanie(fh):
        faza = repo.inplace_op_phase(con, op_id)
        if faza != "written":
            return WriteResult("blocked", PowodPozycji(
                f"operacja {op_id} jest w fazie {faza}, nie 'written' - powrót odmawia",
                "return_not_written", op_id=op_id, phase=faza), None)
        if repo.newer_inplace_op(con, location_id=loc["id"], op_id=op_id):
            return WriteResult("blocked", PowodPozycji(
                f"lokacja ma operację nowszą niż {op_id} - powrót odmawia, żeby nie cofnąć "
                f"późniejszego zapisu", "return_newer_op", op_id=op_id), None)
        st = os.fstat(fh.fileno())
        if st.st_size != spec.file_size or (spec.file_ino and st.st_ino
                                            and st.st_ino != spec.file_ino):
            return WriteResult("blocked", _INNY_PLIK, None)
        fh.seek(spec.region_offset)
        biezacy = fh.read(len(spec.new_region))
        if not _stan_posredni(biezacy, spec):
            return WriteResult("blocked", PowodPozycji(
                f"region nagłówka nie jest ani wynikiem operacji {op_id}, ani stanem pośrednim jej "
                f"powrotu; {_RECZNA}", "return_region_foreign", op_id=op_id, way=_RECZNA), None)
        if biezacy == spec.new_region:
            try:
                niezgodne = _kontrola_danych(_skan_kontrolny(path, kontrola), loc["sha1_data"],
                                             kontrola)
            except Exception as exc:  # noqa: BLE001 - czkawka odczytu nie jest werdyktem
                blad = _blad_systemu(exc)
                return WriteResult("failed", PowodPozycji(
                    f"odczyt kontrolny padł - {blad}; {ponow}", "return_read_failed", detail=blad,
                    way=ponow), None)
            if niezgodne is None:
                return WriteResult("blocked", PowodPozycji(
                    f"kontrola danych operacji {op_id} przechodzi - zapis jest poprawny, powrót go "
                    f"nie cofa; dokończ: {_droga_dokoncz(op_id)}", "return_check_passes",
                    op_id=op_id, way=_droga_dokoncz(op_id)), None)
        else:
            niezgodne = PowodPozycji("przerwany wcześniejszy powrót tej operacji", "return_resumed")
        res = _odzysk_pod_blokada(fh, path, spec)
        if res.status != "applied":
            return WriteResult(res.status, _dopisz(res.reason, ponow), None)
        return _zwolnij_do_skanu(con, op_id, faza, niezgodne, now=now, ponow=ponow)
    wynik = _pod_blokada(path, _dzialanie)
    status = "restored" if wynik.status == "applied" else wynik.status
    return FileResult(loc["id"], path, status, wynik.reason)


def _zwolnij_do_skanu(con, op_id, faza, niezgodne, *, now, ponow) -> WriteResult:
    """KROK KOŃCOWY DROGI POWROTU, wspólny dla fazy `written` (`_powrot_z_written`) i operacji
    OTWARTEJ (`recover_torn`, AR-17 (6)) - wołany pod blokadą pliku, gdy stary region JUŻ stoi
    w miejscu, a kontrola danych nie przeszła (`niezgodne`). JEDNA transakcja
    `repo.revert_inplace_op` z CAS fazy `faza` przeczytanej pod tą blokadą: `recovered` z powodem,
    wpisy stagingu operacji 'failed' z tym samym powodem, `location.mtime` → NULL (pełny skan).
    Porażka transakcji → 'failed' z `ponow`: operacja zostaje w swojej fazie, a ponowienie jest
    bezpieczne - region stary to też stan pośredni, więc drugi przebieg nic nie pisze."""
    prawda = PowodPozycji(f"plik zmienił się poza nagłówkiem od ostatniego skanu albo przy zapisie "
                          f"({niezgodne}) - zapis cofnięty: stary nagłówek przywrócony w miejscu "
                          f"(operacja {op_id}), przeskanuj plik", "reverted_rescan",
                          inner=niezgodne, op_id=op_id)
    try:
        repo.revert_inplace_op(con, op_id=op_id, now=now, reason=prawda, expect_phase=faza)
    except Exception as exc:  # noqa: BLE001
        blad = _blad_systemu(exc)
        return WriteResult("failed", PowodPozycji(
            f"stary nagłówek przywrócony, ale faza 'recovered' NIE zapisana ({blad}); {ponow}",
            "revert_phase_not_saved", detail=blad, way=ponow), None)
    return WriteResult("applied", prawda, None)


def release_isolation(con, op_id, *, now, reason) -> FileResult:
    """ZWOLNIENIE IZOLACJI RĘKĄ (gest „Zwolnij plik do skanu…"): klinga `repo.release_inplace_op`
    wołana POD TĄ SAMĄ blokadą pliku (`_exclusive`), którą trzymają zapis w miejscu, odzysk
    (`recover_torn`) i dokończenie (`finish_inplace`), z fazą przeczytaną OD NOWA pod blokadą
    i podaną klindze jako CAS (`expect_phase`). Zwraca `FileResult` ('released' | 'blocked' |
    'failed'); plik nietknięty w każdej drodze.

    DLACZEGO BLOKADA: izolacja jest jedyną rzeczą, która trzyma skan z dala od pliku w trakcie
    zapisu w miejscu. Zwolnienie bez blokady, gdy drugi proces właśnie pisze albo przywraca region,
    wpuściłoby skan na rozdarty nagłówek, a CAS pisarza zauważyłby zmianę fazy dopiero po fakcie.
    Pod blokadą zwolnienie czeka na koniec zapisu (ponowienia `_LOCK_RETRY_DELAYS`), a gdy plik
    dalej jest trzymany - odmawia ('blocked') z drogą dalej.

    PLIK, KTÓREGO NIE DA SIĘ OTWORZYĆ (skasowany, udział odłączony, brak praw): zwolnienie idzie BEZ
    blokady, bo to droga ręki właśnie dla pliku, którego nie ma - nie może zależeć od tego, że plik
    da się otworzyć. Blokada broni wyłącznie przed procesem, który trzyma plik otwarty do zapisu,
    a to Windows zgłasza przy otwarciu naruszeniem współdzielenia (`_LOCK_TRANSIENT`); każdy inny
    błąd otwarcia znaczy, że pisarz też tego pliku nie otworzy (otwiera go tą samą drogą,
    `OPEN_EXISTING`), więc nie ma zapisu, który zwolnienie mogłoby przeciąć. Faza idzie przez CAS
    klingi także wtedy, a wynik niesie błąd otwarcia jako powód - człowiek widzi, że zwolnił plik,
    którego program nie mógł otworzyć."""
    op = con.execute("SELECT location_id FROM inplace_op WHERE id = ?", (op_id,)).fetchone()
    if op is None:
        return FileResult(0, "", "failed", _brak_operacji(op_id))
    loc = _location(con, int(op["location_id"]))
    if loc is None:
        return FileResult(int(op["location_id"]), "", "failed", _BRAK_LOCATION)
    path = loc["path"]
    wynik = None
    otwarty = False
    try:
        with _exclusive(path):
            otwarty = True
            wynik = _zwolnij_reka(con, op_id, now=now, reason=reason)
    except Exception as exc:  # noqa: BLE001 - raport zamiast wyjątku w warstwie zapisu
        if otwarty and wynik is None:
            return FileResult(loc["id"], path, "failed", _blad_systemu(exc))
        if not otwarty and getattr(exc, "winerror", None) in _LOCK_TRANSIENT:
            return FileResult(loc["id"], path, "blocked", PowodPozycji(
                "plik jest otwarty do zapisu przez inny proces (zapis albo odzysk nagłówka "
                "w toku) - zwolnienie czeka na jego koniec, żeby skan nie przeczytał rozdartego "
                "nagłówka; ponów po zakończeniu tamtego zapisu", "release_file_busy"))
        if not otwarty:
            wynik = _zwolnij_reka(con, op_id, now=now, reason=reason,
                                  bez_blokady=_blad_systemu(exc))
        # otwarty z wynikiem: padło dopiero zamknięcie uchwytu - fakt w bazie zostaje (`_pod_blokada`)
    status, powod = wynik
    return FileResult(loc["id"], path, status, powod)


def _zwolnij_reka(con, op_id, *, now, reason, bez_blokady=None) -> tuple[str, str | None]:
    """Rdzeń `release_isolation`: faza czytana TERAZ (pod blokadą pliku albo - `bez_blokady` -
    przy pliku, którego nie da się otworzyć) i klinga z CAS tej fazy. `(status, powód)`; nie rzuca."""
    try:
        faza = repo.inplace_op_phase(con, op_id)
        if faza not in repo.INPLACE_ISOLATING_PHASES:
            return "blocked", PowodPozycji(f"operacja {op_id} nie izoluje już lokacji (faza "
                                           f"{faza}) - nie ma czego zwalniać",
                                           "release_not_isolating", op_id=op_id, phase=faza)
        repo.release_inplace_op(con, op_id=op_id, now=now, reason=reason, expect_phase=faza)
    except ValueError as exc:                      # CAS: faza zmieniona w międzyczasie
        # Odmowa klingi z kodem (`OdmowaZPowodem` to `ValueError`): tekst = `str(exc)` bez zmian.
        return "blocked", powod_wyjatku(exc)
    except Exception as exc:  # noqa: BLE001
        return "failed", _blad_systemu(exc)
    if bez_blokady is not None:
        return "released", PowodPozycji(f"pliku nie da się otworzyć ({bez_blokady}) - zwolniono "
                                        f"bez blokady pliku", "released_without_lock",
                                        detail=bez_blokady)
    return "released", None


# ============================================================ ZMIANA OBIEKTU RAZEM Z PLIKIEM (AR-17 krok 3)
# Gest „Zmień obiekt…” i „Uzgodnij” (D-1011-5): per POZYCJA (klatka z jedną obecną kopią) baza →
# przeniesienie → karta, razem albo wcale; cofnięcie per pozycja karta → plik → baza, z fazą w bazie;
# katalogi na końcu przebiegu. Plan: `object_change.plan_object_change`, staging:
# `repo.stage_object_change`. Sterownik i cofnięcie odtwarzają przebieg WYŁĄCZNIE z bazy (`run_id`),
# więc przeżywają awarię procesu. W GUI to JEDNA operacja pisarza - dwa starty `WritebackRunner`
# zwalniają między sobą mutex Dostawy (`gui/wb_worker.py`).

_GEST = "object_change"                  # ładunek `location.renamed` przeniesienia gestu
_GEST_POWROTU = "object_change_undo"     # ... i powrotu pliku (cofnięcie, odmowa karty w biegu)


def _uwaga_niepewnej_wlasnosci(katalog) -> ZdanieRdzenia:
    """Ostrzeżenie: katalog z zamiarem założenia bez potwierdzenia, który istnieje - własność
    niepewna. Kod `dir_uncertain` - zdanie okna `objchg.warn.dir_uncertain` (AR-138)."""
    return ZdanieRdzenia(f"katalog {katalog}: zamiar założenia bez potwierdzenia, a katalog "
                         f"istnieje - własność niepewna, zostaje do oka", "dir_uncertain",
                         dir=katalog)


def _ostrzezenia_rekoncyliacji(con, *, now) -> list[ZdanieRdzenia]:
    """Ostrzeżenia gestu z rekoncyliacji przerwanych renamów na wejściu (zamiar, którego dysk nie
    rozstrzygnął): „ścieżka: powód” z kodem `rename_reconcile` - okno mówi je w języku UI, powód
    rekoncyliacji (z kodem) jako parametr `detail` (AR-148; dawniej goły f-string)."""
    return [ZdanieRdzenia(f"{r.path}: {r.reason}", "rename_reconcile", path=r.path, detail=r.reason)
            for r in reconcile_renames(con, now=now) if r.status == "blocked"]


@dataclasses.dataclass(frozen=True)
class ObjectChangeResult:
    """Wynik przebiegu gestu zmiany obiektu (`commit_object_change`) albo jego cofnięcia
    (`undo_object_change`) - per POZYCJA (plik pary), nie per wpis stagingu.

    Zapis: `applied` (baza, plik i karta pozycji zgodne z celem), `blocked` (odmowa - kroki pozycji
    wróciły, plik i baza jak przed gestem), `failed` (stan częściowy - powód niesie drogę dalej:
    cofnięcie przebiegu albo odzysk karty), `skipped` (dryf, kopia zniknęła - nic nie zrobiono).
    Cofnięcie: `applied` = pozycje cofnięte (status 'restored', powód = uwaga, np. nowsza decyzja
    ręki w bazie), `blocked`/`failed` = zatrzymane z powodem (ponowienie wznawia fazę), `skipped` =
    pozycje, do których zapis nie doszedł (nie było czego cofać).

    `commit_ids` = WSZYSTKIE commity kart przebiegu (ponowienie po awarii dokłada nowy). Katalogi:
    `dirs_created` (zapis: założone katalogi celu, cofnięcie: odtworzone stare), `dirs_removed`
    (zapis: źródłowe opróżnione przez gest i własne puste po odmowie, cofnięcie: założone przez
    gest), `dirs_uncertain` (zamiar założenia bez potwierdzenia przy istniejącym katalogu - nigdy nie
    usuwany automatycznie, ścieżki w `warnings`). `warnings` - zdania dla człowieka bez blokady
    (`ZdanieRdzenia` z kodem i parametrami albo zwykły `str`).

    `withheld` (AR-82): przy zapisie - osobny kubeł pozycji, których karta jest ZAPISANA, a zeznanie
    klatki jej nie przyjęło (pozycja 'failed' do dokończenia); przy cofnięciu - podzbiór `applied`,
    którego karta wróciła do pliku, a zeznanie klatki nie (czytane z bazy, przeżywa wznowienie)."""
    run_id: str
    applied: list[FileResult]
    blocked: list[FileResult]
    failed: list[FileResult]
    skipped: list[FileResult]
    commit_ids: tuple[int, ...] = ()
    dirs_created: int = 0
    dirs_removed: int = 0
    dirs_uncertain: int = 0
    cancelled: bool = False
    warnings: tuple[str, ...] = ()
    withheld: list[FileResult] = dataclasses.field(default_factory=list)


def _przebieg_zmiany(con, run_id):
    return con.execute("SELECT run_id, mode, status FROM object_change_run WHERE run_id = ?",
                       (run_id,)).fetchone()


def _pozycje_przebiegu(con, run_id):
    """Pozycje przebiegu z wierszem przeniesienia, w kolejności stagingu. Ścieżka i `mtime` podglądu
    z wiersza POZYCJI (każda je ma), nowa ścieżka i stan ruchu z wiersza przeniesienia."""
    return con.execute(
        "SELECT p.id, p.run_id, p.frame_id, p.location_id, p.object_change, p.object_id, p.status, "
        "       p.undo_phase, p.rename_id, p.mkdirs, p.old_path, p.expected_mtime, r.new_path, "
        "       r.status AS rename_status, r.in_flight "
        "FROM pending_object_change p LEFT JOIN pending_renames r ON r.id = p.rename_id "
        "WHERE p.run_id = ? ORDER BY p.id", (run_id,)).fetchall()


def _karty_lokacji(con, run_id, location_id):
    """Wpisy stagingu karty pozycji (przebieg + lokacja), w kolejności stagingu; powód wpisu czyta
    `_powod_wiersza`."""
    return con.execute(
        "SELECT id, location_id, keyword, idx, op, old_value, new_value, new_type, new_comment, "
        "       expected_header_hash, status, reason, reason_code, reason_args, withheld_id "
        "FROM pending_changes WHERE run_id = ? AND location_id = ? ORDER BY id",
        (run_id, location_id)).fetchall()


def _status_renamu(con, rename_id):
    row = con.execute("SELECT status FROM pending_renames WHERE id = ?", (rename_id,)).fetchone()
    return None if row is None else row["status"]


def _katalogi_przebiegu(con, run_id):
    return con.execute("SELECT id, path, action, done_at, undone_at FROM run_dir "
                       "WHERE run_id = ? ORDER BY id", (run_id,)).fetchall()


def _commity_przebiegu(con, run_id) -> tuple[int, ...]:
    """Commity kart przebiegu z backupem do cofnięcia - WSZYSTKIE (ponowienie dokłada nowy)."""
    return tuple(r[0] for r in con.execute(
        "SELECT DISTINCT c.id FROM commits c JOIN header_backups b ON b.commit_id = c.id "
        "WHERE c.run_id = ? AND b.unreplaced_at IS NULL ORDER BY c.id", (run_id,)))


def _backupy_lokacji(con, run_id, location_id):
    """Backupy kart pozycji ze WSZYSTKICH commitów przebiegu, od najnowszego (cofnięcie jak stos)."""
    return con.execute(
        "SELECT b.id, b.commit_id, b.location_id, b.hdu_index, b.header_text, b.post_hash "
        "FROM header_backups b JOIN commits c ON c.id = b.commit_id "
        "WHERE c.run_id = ? AND b.location_id = ? AND b.unreplaced_at IS NULL ORDER BY b.id DESC",
        (run_id, location_id)).fetchall()


def _glebokosc(sciezka) -> int:
    return len(os.path.normpath(sciezka).split(os.sep))


def _poziomy_pod(wspolny, katalog) -> list[str]:
    """Katalogi od `wspolny` (bez niego) w dół do `katalog` włącznie, od najpłytszego - jedyny
    zakres, w którym gest zakłada i usuwa katalogi źródła: wspólny przodek starej i nowej ścieżki
    niesie też cel, więc nie jest nigdy kandydatem. EXPECT: `katalog` leży pod `wspolny`."""
    rel = os.path.relpath(katalog, wspolny)
    if rel == os.curdir:
        return []
    if rel == os.pardir or rel.startswith(os.pardir + os.sep) or os.path.isabs(rel):
        raise ValueError(f"{katalog} nie leży pod {wspolny}")
    poziomy, biezacy = [], wspolny
    for czesc in rel.split(os.sep):
        biezacy = os.path.join(biezacy, czesc)
        poziomy.append(biezacy)
    return poziomy


def _wspolny_przodek(p) -> str:
    return os.path.commonpath([os.path.dirname(p["old_path"]), os.path.dirname(p["new_path"])])


def _pusty_katalog(sciezka) -> bool:
    try:
        return os.path.isdir(sciezka) and not os.listdir(sciezka)
    except OSError:
        return False


def _zaloz_katalogi(con, run_id, katalogi, *, now, akcja) -> tuple[str | None, int]:
    """Załóż brakujące katalogi z listy (od najpłytszego) - KAŻDY z zamiarem w `run_dir`
    zatwierdzonym WŁASNĄ transakcją PRZED `os.mkdir` i `done_at` po nim (D-1011-5 Q3). Dzieje się
    PRZED strażą renamu, nigdy w niej: zapis katalogu w transakcji relokacji wiązałby jej rollback
    z mutacją, której rollback nie cofnie. Katalog, który już istnieje, nie jest nasz - bez wiersza.
    `os.mkdir`, nie `os.makedirs` ani `os.renames`: rodzic każdego poziomu istnieje z konstrukcji
    listy, a poziom spoza listy nie powstanie bez zapisu (brak rodzica = odmowa); `os.renames`
    kasowałby przy okazji puste katalogi źródła. Katalog założony przez kogoś między sprawdzeniem
    a `mkdir` zostawia zamiar bez `done_at` = własność niepewna (nigdy nie usuwany automatycznie).
    → `(powód odmowy | None, ile założono)`; po odmowie plik nie jest ruszany."""
    zalozone = 0
    for katalog in katalogi:
        if os.path.isdir(katalog):
            continue
        try:
            dir_id = repo.open_run_dir(con, run_id=run_id, path=katalog, action=akcja, now=now)
        except Exception as exc:  # noqa: BLE001 - bez zamiaru katalogu nie zakładamy
            blad = _blad_systemu(exc)
            return PowodPozycji(f"zamiar katalogu {katalog} nie zapisany ({blad}) - katalogu nie "
                                f"założono, pliku nie ruszono", "dir_intent_failed", dir=katalog,
                                detail=blad), zalozone
        try:
            os.mkdir(katalog)
        except FileExistsError:
            continue                     # ktoś zdążył przed nami - zamiar zostaje bez `done_at`
        except OSError as exc:
            blad = _blad_systemu(exc)
            return PowodPozycji(f"katalogu {katalog} nie da się założyć ({blad}) - pliku nie "
                                f"ruszono", "dir_create_failed", dir=katalog, detail=blad), zalozone
        zalozone += 1
        try:
            repo.finish_run_dir(con, dir_id=dir_id, now=now)
        except Exception as exc:  # noqa: BLE001 - katalog jest, potwierdzenia nie ma
            blad = _blad_systemu(exc)
            return PowodPozycji(f"katalog {katalog} założony, ale jego potwierdzenie w bazie padło "
                                f"({blad}) - zostaje do oka, pliku nie ruszono", "dir_unconfirmed",
                                dir=katalog, detail=blad), zalozone
    return None, zalozone


def _usun_katalog(con, run_id, katalog, *, now) -> ZdanieRdzenia | None:
    """Usuń PUSTY katalog źródłowy, który gest opróżnił: zamiar `removed` własną transakcją PRZED
    `os.rmdir` (tylko pusty - na niepustym rzuca), `done_at` po nim. → ostrzeżenie porażki albo
    None."""
    try:
        dir_id = repo.open_run_dir(con, run_id=run_id, path=katalog, action="removed", now=now)
        os.rmdir(katalog)
    except Exception as exc:  # noqa: BLE001 - katalog zostaje; to nie blokuje przebiegu
        blad = _blad_systemu(exc)
        return ZdanieRdzenia(f"katalog {katalog} nie usunięty ({blad})", "dir_not_removed",
                             dir=katalog, detail=blad)
    repo.finish_run_dir(con, dir_id=dir_id, now=now)
    return None


def _usun_wlasne_puste(con, run_id, *, now) -> tuple[int, list[str]]:
    """Katalogi założone przez gest (`created` z `done_at`, bez `undone_at`) - od najgłębszego:
    pusty → `os.rmdir` + `undone_at`, już nieistniejący → `undone_at`, niepusty → zostaje (lista).
    Wyłącznie własność pewna: zamiar bez `done_at` nigdy tu nie wchodzi. → (ile usunięto, niepuste)."""
    usuniete, niepuste = 0, []
    wlasne = [d for d in _katalogi_przebiegu(con, run_id) if d["action"] == "created"
              and d["done_at"] is not None and d["undone_at"] is None]
    for d in sorted(wlasne, key=lambda d: _glebokosc(d["path"]), reverse=True):
        if not os.path.isdir(d["path"]):
            repo.undo_run_dir(con, dir_id=d["id"], now=now)
            continue
        if not _pusty_katalog(d["path"]):
            niepuste.append(d["path"])
            continue
        try:
            os.rmdir(d["path"])
        except OSError:
            niepuste.append(d["path"])
            continue
        repo.undo_run_dir(con, dir_id=d["id"], now=now)
        usuniete += 1
    return usuniete, niepuste


def _rekoncyliuj_katalogi(con, run_id, *, now) -> None:
    """Zamiary katalogów bez `done_at` (awaria między zamiarem a potwierdzeniem) - rozstrzyga dysk:
    `removed`, którego katalogu nie ma → zaszło; `restored`, którego katalog jest → zaszło. `created`
    bez `done_at` zostaje, jak jest: katalogu nie ma = mutacji nie było (następne założenie otworzy
    zamiar od nowa), katalog jest = własność niepewna (`_niepewne_katalogi`)."""
    for d in _katalogi_przebiegu(con, run_id):
        if d["done_at"] is not None:
            continue
        jest = os.path.isdir(d["path"])
        if (d["action"] == "removed" and not jest) or (d["action"] == "restored" and jest):
            repo.finish_run_dir(con, dir_id=d["id"], now=now)


def _niepewne_katalogi(con, run_id) -> list[str]:
    return [d["path"] for d in _katalogi_przebiegu(con, run_id)
            if d["action"] == "created" and d["done_at"] is None and os.path.isdir(d["path"])]


def _przenies_wstecz(con, p, *, now, reason) -> RenameFileResult:
    """Powrót pliku pozycji pod starą ścieżkę - ta sama straż co przeniesienie (izolacja, generacja,
    cel wolny w bazie, relokacja w transakcji renamu), wiersz przeniesienia → 'skipped' z powodem."""
    gen = repo.inplace_generation(con)
    izolujaca = repo.isolating_inplace_op(con, p["location_id"])
    if izolujaca is not None:
        return RenameFileResult("blocked", _powod_izolacji(izolujaca))
    loc = _location_rename(con, p["location_id"])
    if loc is None or path_key(loc["path"]) != path_key(p["new_path"]):
        return RenameFileResult("blocked", PowodPozycji("plik nie stoi na ścieżce z przebiegu",
                                                        "not_on_run_path"))
    return _rename_pod_straza(con, rename_id=p["rename_id"], kierunek="undo",
                              location_id=p["location_id"], old_path=p["new_path"],
                              new_path=p["old_path"], generation=gen, now=now, status="skipped",
                              reason=reason, gest=_GEST_POWROTU)


def _wycofaj_pozycje(con, p, status, powod, *, now, przeniesiony, code=None) -> FileResult:
    """ODMOWA POZYCJI („razem albo wcale”, D-1011-5 Q2): kroki zrobione dla niej wracają - plik pod
    starą ścieżkę, baza przez CAS klingi - a pozycja dostaje `status` z powodem (i `code` odmowy
    pisarza, gdy ją niesie). Wpisy stagingu, do których nie doszło, dostają ten sam status (szuflada
    nie pokaże ich jako oczekujących). Plik, który nie wrócił, to stan częściowy: 'failed' z drogą
    dalej (cofnięcie przebiegu), a baza zostaje przy nowym obiekcie - zgodna z miejscem pliku."""
    lid = p["location_id"]
    if przeniesiony:
        wynik = _przenies_wstecz(con, p, now=now, reason=PowodPozycji(
            f"{_COFNIETO} - {powod}", "rename_undone_because", inner=powod))
        if wynik.status != "applied":
            powod = PowodPozycji(
                f"{powod}; plik NIE wrócił pod {p['old_path']} ({wynik.reason}) - zostaje pod nową "
                f"ścieżką, baza pozycji jak po zapisie; drogą dalej jest cofnięcie przebiegu",
                "file_not_back", outer=powod, path=p["old_path"], inner=wynik.reason)
            repo.settle_object_change_item(con, item_id=p["id"], status="failed", reason=powod,
                                           now=now)
            return FileResult(lid, p["new_path"], "failed", powod)
    _rozlicz_wpisy(con, p, status, powod)
    repo.settle_object_change_item(con, item_id=p["id"], status=status, reason=powod, now=now,
                                   restore=True)
    loc = _location_rename(con, lid)
    return FileResult(lid, "" if loc is None else loc["path"], status, powod, code=code)


def _dryf_po_wznowieniu(con, p, *, now, przeniesiony) -> FileResult:
    """WZNOWIENIE pozycji, której klatka nie niesie już wyniku kroku bazy sprzed awarii (nowsza
    decyzja ręki albo martwa tożsamość): ani baza, ani plik nie są dalej ruszane - starsza decyzja
    nie wraca, a plik nie idzie za obiektem, którego klatka już nie ma. Nic z gestu nie zostało
    (wynik w bazie zapomniany przez klingę, plik nieprzeniesiony) → 'skipped'; inaczej 'failed' -
    resztę gestu zdejmuje cofnięcie przebiegu."""
    zostalo = przeniesiony or con.execute(
        "SELECT object_id FROM pending_object_change WHERE id = ?", (p["id"],)).fetchone()[0] \
        is not None
    if zostalo:
        powod = PowodPozycji("obiekt klatki zmienił się po kroku bazy tej pozycji (przed awarią) - "
                             "plik nie jest dalej ruszany; resztę gestu zdejmuje cofnięcie "
                             "przebiegu", "drift_resumed_undo")
    else:
        powod = PowodPozycji("obiekt klatki zmienił się po kroku bazy tej pozycji (przed awarią) - "
                             "plik nie jest dalej ruszany", "drift_resumed")
    status = "failed" if zostalo else "skipped"
    _rozlicz_wpisy(con, p, "skipped", powod)
    repo.settle_object_change_item(con, item_id=p["id"], status=status, reason=powod, now=now)
    loc = _location_rename(con, p["location_id"])
    return FileResult(p["location_id"], "" if loc is None else loc["path"], status, powod)


def _rozlicz_wpisy(con, p, status, powod) -> None:
    """Wpisy stagingu pozycji, do których zapis nie doszedł (przeniesienie i karta wciąż 'pending'),
    dostają status pozycji z powodem - szuflada nie pokaże ich jako oczekujących."""
    if p["rename_id"] is not None and _status_renamu(con, p["rename_id"]) == "pending":
        repo.set_rename_status(con, rename_id=p["rename_id"], status=status, reason=powod)
    for r in _karty_lokacji(con, p["run_id"], p["location_id"]):
        if r["status"] == "pending":
            repo.set_pending_status(con, pending_id=r["id"], status=status, reason=powod)


def _zmien_pozycje(con, stan, p, *, now, liczniki) -> FileResult:
    """JEDNA POZYCJA gestu (D-1011-5 Q1/Q2, baza per pozycja): bramki bez zapisu → (1) baza (CAS ręki
    i stan sprzed jedną transakcją) → (2) przeniesienie (katalogi celu z zamiarem przed `mkdir`,
    rename pod strażą) → (3) karta (ciało `commit` per lokacja, w miejscu ze spadkiem na drogę
    atomową). Odmowa (2) albo (3) BEZ zapisu = zrobione kroki pozycji wracają, status 'blocked'.
    Karta po zapisie częściowym (rozdarta, bez re-syncu) = plik zostaje, lokacja izolowana, 'failed'
    z drogą naprawy. Krok zrobiony przed awarią (`object_id` w wierszu, przeniesienie 'applied',
    karta 'applied') nie powtarza się - ponowienie idzie od pierwszego niezrobionego."""
    lid = p["location_id"]
    gen = repo.inplace_generation(con)      # PRZED bramką izolacji - dla straży renamu
    loc = _location(con, lid)
    karty = _karty_lokacji(con, stan.run_id, lid)
    oczekujace = [r for r in karty if r["status"] == "pending"]
    przeniesiony = p["rename_id"] is not None and p["rename_status"] == "applied"

    def _odmowa(status, powod, code=None):
        return _wycofaj_pozycje(con, p, status, powod, now=now, przeniesiony=przeniesiony,
                                code=code)

    if p["rename_id"] is not None and p["in_flight"] is not None:
        # Przerwana próba, której rekoncyliacja nie rozstrzygnęła: plik może stać pod którąkolwiek
        # nazwą - to nie jest odmowa „bez zapisu”, tylko stan do rozstrzygnięcia.
        repo.settle_object_change_item(con, item_id=p["id"], status="failed",
                                       reason=_ZAMIAR_OTWARTY, now=now)
        return FileResult(lid, p["old_path"], "failed", _ZAMIAR_OTWARTY)
    # Każdy powód pozycji to `PowodPozycji` (AR-141): zdanie PL jak dotąd, kod i parametry dla okna
    # - także po zapisie w bazie (`repo._set_object_change_reason_tx`).
    if loc is None:
        return _odmowa("skipped", PowodPozycji("brak location w bazie", "no_location"))
    if not loc["present"]:
        return _odmowa("skipped", PowodPozycji("kopia zniknęła (present=0)", "copy_gone"))
    izolujaca = repo.isolating_inplace_op(con, lid)
    if izolujaca is not None:
        return _odmowa("blocked", _powod_izolacji(izolujaca))
    # KOTWICE PODGLĄDU, KAŻDA POZYCJA: kopia stoi tam, gdzie pokazał ją podgląd (po przeniesieniu
    # zrobionym przed awarią - pod nową ścieżką), porównanie fizyczne jak przy kolizji (`R:` nie
    # rozróżnia wielkości liter). Przed mutacją pliku także `mtime` z podglądu w bazie I NA DYSKU:
    # zmiana pliku, której skan jeszcze nie wciągnął (karta przepisana innym programem), ma inny
    # `mtime` na dysku - gest nie zawiezie do folderu obiektu pliku, którego podgląd nie widział.
    tutaj = p["new_path"] if przeniesiony else p["old_path"]
    if path_key(loc["path"]) != path_key(tutaj):
        return _odmowa("blocked", PowodPozycji("kopia stoi pod inną ścieżką niż w podglądzie - "
                                               "odśwież podgląd", "path_moved"))
    if oczekujace or (p["rename_id"] is not None and not przeniesiony):
        if p["expected_mtime"] is None:
            return _odmowa("blocked", PowodPozycji("kopia bez kotwicy mtime z podglądu - gest nie "
                                                   "wie, czy to ten sam plik", "no_mtime_anchor"))
        if loc["mtime"] != p["expected_mtime"]:
            return _odmowa("blocked", PowodPozycji("plik zmieniony od podglądu (mtime w bazie) - "
                                                   "odśwież podgląd", "changed_since_preview"))
        try:
            na_dysku = scan._mtime_iso(os.stat(loc["path"]))
        except OSError as exc:
            blad = _blad_systemu(exc)
            return _odmowa("blocked", PowodPozycji(f"plik nieosiągalny przed zapisem ({blad})",
                                                   "unreachable", detail=blad))
        if na_dysku != p["expected_mtime"]:
            return _odmowa("blocked", PowodPozycji("plik zmieniony od ostatniego skanu - Dostawa, "
                                                   "potem gest ponownie", "changed_since_scan"),
                           code=CODE_CHANGED_SINCE_SCAN)
    if p["rename_id"] is not None and not przeniesiony:
        if p["rename_status"] != "pending":
            return _odmowa("blocked", PowodPozycji(
                f"przeniesienie odbite w poprzedniej próbie (status {p['rename_status']}) - "
                f"odśwież podgląd", "rename_bounced", status=p["rename_status"]))
        kolizja = repo.path_owner(con, volume=loc["volume"], path=p["new_path"], location_id=lid)
        if kolizja is not None:
            return _odmowa("blocked", PowodPozycji(f"cel zajęty w bazie (location:{kolizja})",
                                                   "target_taken", location=kolizja))
    if oczekujace and (oczekujace[0]["expected_header_hash"] is None
                       or loc["header_hash"] != oczekujace[0]["expected_header_hash"]):
        return _odmowa("blocked", PowodPozycji("nagłówek zmieniony od podglądu albo bez kotwicy "
                                               "(header_hash) - karta nie wejdzie; odśwież podgląd",
                                               "header_changed"))

    # (1) BAZA
    try:
        werdykt = repo.apply_object_change_item(con, item_id=p["id"], now=now)
    except ValueError as exc:
        # Odmowa klingi z kodem (konflikt aliasu, nagrobek przez parę xref - `OdmowaZPowodem`)
        # albo EXPECT prozą (`powod_wyjatku`).
        odmowa = powod_wyjatku(exc)
        return _odmowa("blocked", PowodPozycji(f"zmiana obiektu odmówiona: {odmowa}", "db_refused",
                                               inner=odmowa))
    if werdykt == "copies":
        return _odmowa("blocked", PowodPozycji(
            "klatka nie ma dokładnie jednej obecnej kopii, tej z podglądu - kopia wjechała albo "
            "zniknęła po podglądzie; odśwież podgląd", "copies_changed"))
    if werdykt == "drift" and p["object_id"] is not None:
        return _dryf_po_wznowieniu(con, p, now=now, przeniesiony=przeniesiony)
    if werdykt == "drift":
        return _odmowa("skipped", PowodPozycji("obiekt klatki zmienił się od podglądu (dryf) - "
                                               "pozycja nietknięta; odśwież podgląd", "drift"))

    # (2) PRZENIESIENIE
    if p["rename_id"] is not None and not przeniesiony:
        powod, zalozone = _zaloz_katalogi(con, stan.run_id, json.loads(p["mkdirs"]), now=now,
                                          akcja="created")
        liczniki["created"] += zalozone
        if powod is not None:
            return _odmowa("blocked", powod)
        katalog_celu = os.path.dirname(p["new_path"])
        if not os.path.isdir(katalog_celu):
            return _odmowa("blocked", PowodPozycji(
                f"katalog celu {katalog_celu} nie istnieje, a podgląd go nie zakładał - odśwież "
                f"podgląd", "target_dir_missing", dir=katalog_celu))
        ruch = _rename_pod_straza(con, rename_id=p["rename_id"], kierunek="commit", location_id=lid,
                                  old_path=p["old_path"], new_path=p["new_path"], generation=gen,
                                  now=now, status="applied", gest=_GEST)
        if ruch.status != "applied":
            repo.set_rename_status(con, rename_id=p["rename_id"],
                                   status="failed" if ruch.status == "failed" else "blocked",
                                   reason=ruch.reason)
            if ruch.torn:
                powod = PowodPozycji(f"{ruch.reason}; baza pozycji jak po kroku bazy - miejsce "
                                     f"pliku rozstrzyga rekoncyliacja renamu, drogą dalej jest "
                                     f"cofnięcie przebiegu", "rename_torn", inner=ruch.reason)
                repo.settle_object_change_item(con, item_id=p["id"], status="failed", reason=powod,
                                               now=now)
                return FileResult(lid, p["old_path"], "failed", powod)
            return _odmowa("blocked", ruch.reason)
        przeniesiony = True

    # (3) KARTA
    uwaga = kod = None
    if oczekujace:
        zapis = _zapisz_lokacje(con, stan, lid, oczekujace, now=now, inplace=True, fallback=True)
        if zapis.wynik.status == "withheld":
            # AR-82: karta ZAPISANA, zeznanie klatki jej nie przyjęło - pozycja ma już 'failed'
            # (stan częściowy w Porządkach) z prawdziwym powodem, nadany W TRANSAKCJI wstrzymania
            # (`repo._withhold_write_tx`, B4). Sterownik jej nie przestawia: dokończenie z innego
            # połączenia mogło ją już domknąć ('applied') i nadpisanie cofnęłoby ten stan.
            return FileResult(lid, zapis.wynik.path, "withheld", zapis.wynik.reason,
                              code=CODE_ZEZNANIE_WSTRZYMANE)
        if zapis.wynik.status != "applied":
            # Powód pisarza karty zostaje prozą w `inner` (warstwa bez kodu - granica AR-141).
            if not zapis.dotknieto:
                return _odmowa("blocked", PowodPozycji(
                    f"karta odbita bez zapisu: {zapis.wynik.reason}", "card_refused",
                    inner=zapis.wynik.reason), code=zapis.wynik.code)
            powod = PowodPozycji(
                f"karta zapisana częściowo: {zapis.wynik.reason}; plik zostaje pod "
                f"{zapis.wynik.path}, baza pozycji jak po zapisie - najpierw naprawa karty wg "
                f"powodu, potem ewentualnie cofnięcie przebiegu", "card_partial",
                inner=zapis.wynik.reason, path=zapis.wynik.path)
            repo.settle_object_change_item(con, item_id=p["id"], status="failed", reason=powod,
                                           now=now)
            return FileResult(lid, zapis.wynik.path, "failed", powod)
        uwaga, kod = zapis.wynik.reason, zapis.wynik.code
    elif karty and any(r["status"] != "applied" for r in karty):
        # Wpisy karty rozliczone przed awarią bez zapisu pozycji: 'failed' mógł ruszyć bajty.
        zly = next(r for r in karty if r["status"] != "applied")
        poprzedni = _powod_wiersza(zly)        # z kodem, gdy wpis go niesie (0042, AR-148)
        if zly["withheld_id"] is not None:     # AR-82: karta zapisana, zeznanie wstrzymane
            # Status pozycji nadało wstrzymanie (B4) - bez ponownego rozliczenia.
            return FileResult(lid, loc["path"], "withheld", poprzedni,
                              code=CODE_ZEZNANIE_WSTRZYMANE)
        if zly["status"] == "failed":
            powod = PowodPozycji(f"karta z poprzedniej próby: {poprzedni}", "card_prev_failed",
                                 inner=poprzedni)
            repo.settle_object_change_item(con, item_id=p["id"], status="failed", reason=powod,
                                           now=now)
            return FileResult(lid, loc["path"], "failed", powod)
        return _odmowa("blocked", PowodPozycji(f"karta odbita w poprzedniej próbie: {poprzedni}",
                                               "card_prev_refused", inner=poprzedni))
    repo.settle_object_change_item(con, item_id=p["id"], status="applied", reason=uwaga, now=now)
    teraz = _location_rename(con, lid)
    return FileResult(lid, teraz["path"], "applied", uwaga, code=kod)


def _sprzatnij_po_zapisie(con, run_id, rozliczone, *, now) -> tuple[int, list[str]]:
    """KONIEC PRZEBIEGU ZAPISU (D-1011-5 Q3): (1) katalogi źródłowe, które gest opróżnił W TYM
    PRZEBIEGU (`rozliczone` = id pozycji zapisanych teraz) - od katalogu starej ścieżki w górę do
    wspólnego przodka starej i nowej (bez niego) - usuwane, gdy puste, od najgłębszego, z zamiarem
    `removed` przed `os.rmdir`; (2) katalogi założone przez gest, które zostały puste (przeniesienie
    odbite po założeniu katalogu), usuwane - wyłącznie własność pewna. Katalogu z ZAKOŃCZONYM wpisem
    `removed` (opróżniony i usunięty wcześniej, pod tą ścieżką stoi już cudzy) nie usunie
    `_usun_katalog`: `repo.open_run_dir` nie otwiera takiego wpisu ponownie. → (ile usunięto,
    ostrzeżenia)."""
    kandydaci = {}
    for p in _pozycje_przebiegu(con, run_id):
        if (p["id"] not in rozliczone or p["status"] != "applied" or p["rename_id"] is None
                or p["rename_status"] != "applied"):
            continue
        for katalog in _poziomy_pod(_wspolny_przodek(p), os.path.dirname(p["old_path"])):
            kandydaci.setdefault(os.path.normcase(katalog), katalog)
    usuniete, ostrzezenia = 0, []
    for katalog in sorted(kandydaci.values(), key=_glebokosc, reverse=True):
        if not _pusty_katalog(katalog):
            continue
        powod = _usun_katalog(con, run_id, katalog, now=now)
        if powod is None:
            usuniete += 1
        else:
            ostrzezenia.append(powod)
    wlasne, _ = _usun_wlasne_puste(con, run_id, now=now)
    return usuniete + wlasne, ostrzezenia


def commit_object_change(con, run_id, *, now,
                         progress: Callable[[int, int, str, str], None] | None = None,
                         should_cancel: Callable[[], bool] | None = None) -> ObjectChangeResult:
    """ZAPIS GESTU „Zmień obiekt…”/„Uzgodnij” (D-1011-5, AR-17 krok 3) - przebieg odtworzony z bazy
    (`run_id`): per POZYCJA oczekująca `_zmien_pozycje` (baza → przeniesienie → karta, razem albo
    wcale), na końcu katalogi (źródłowe opróżnione przez gest i własne puste). Pozycja rozliczona
    utrwala się od razu, więc anulowanie (`should_cancel` PRZED pozycją) zostawia resztę 'pending' -
    ponowne wywołanie ją dokończy. `progress(done, total, path, status)` po KAŻDEJ pozycji.

    Na wejściu: rekoncyliacja przerwanych renamów WSZYSTKICH przebiegów (`reconcile_renames`, jak
    `commit_renames`) i zamiarów katalogów tego przebiegu. Przebieg bez pozycji oczekujących (np.
    zapisany wcześniej) = nic poza tą rekoncyliacją - sprzątanie katalogów dotyczy wyłącznie pozycji
    rozliczonych w tym wywołaniu. Przebieg nieznany albo cofany/cofnięty → `ValueError` (EXPECT:
    cofniętego gestu zapis nie wznawia - nowy gest to nowy podgląd)."""
    przebieg = _przebieg_zmiany(con, run_id)
    if przebieg is None:
        raise ValueError(f"przebieg zmiany obiektu {run_id} nie istnieje")
    if przebieg["status"] in ("undoing", "undone"):
        raise ValueError(f"przebieg zmiany obiektu {run_id} jest cofany albo cofnięty - zapis go "
                         f"nie wznowi; nowy gest to nowy podgląd")
    ostrzezenia = _ostrzezenia_rekoncyliacji(con, now=now)
    _rekoncyliuj_katalogi(con, run_id, now=now)
    pozycje = [p for p in _pozycje_przebiegu(con, run_id) if p["status"] == "pending"]
    total = len(pozycje)
    applied: list[FileResult] = []
    blocked: list[FileResult] = []
    failed: list[FileResult] = []
    skipped: list[FileResult] = []
    withheld: list[FileResult] = []
    kubly = {"applied": applied, "blocked": blocked, "failed": failed, "skipped": skipped,
             "withheld": withheld}
    stan = _StanCommitu(run_id, lambda: now)
    liczniki = {"created": 0}
    cancelled = False
    done = 0
    rozliczone = set()
    for p in pozycje:
        if should_cancel is not None and should_cancel():
            cancelled = True
            break
        wynik = _zmien_pozycje(con, stan, p, now=now, liczniki=liczniki)
        rozliczone.add(p["id"])
        kubly[wynik.status].append(wynik)
        done += 1
        if progress is not None:
            progress(done, total, wynik.path, wynik.status)
    usuniete = 0
    if rozliczone:
        usuniete, uwagi = _sprzatnij_po_zapisie(con, run_id, rozliczone, now=now)
        ostrzezenia.extend(uwagi)
    if not cancelled:
        repo.set_object_change_run_status(con, run_id=run_id, status="applied")
    niepewne = _niepewne_katalogi(con, run_id)
    ostrzezenia.extend(_uwaga_niepewnej_wlasnosci(k) for k in niepewne)
    return ObjectChangeResult(run_id, applied, blocked, failed, skipped,
                              _commity_przebiegu(con, run_id), liczniki["created"], usuniete,
                              len(niepewne), cancelled, tuple(ostrzezenia), withheld=withheld)


def _bez_sladu(con, p) -> bool:
    """Pozycja oczekująca, do której zapis nie doszedł: baza nietknięta, plik nie przeniesiony (bez
    zamiaru w locie), karta bez backupu w przebiegu - cofnięcie nie ma tu czego cofać."""
    return (p["object_id"] is None and p["in_flight"] is None
            and p["rename_status"] in (None, "pending", "blocked", "failed", "skipped")
            and not _backupy_lokacji(con, p["run_id"], p["location_id"]))


def _cofnij_pozycje(con, p, *, now, liczniki) -> FileResult:
    """COFNIĘCIE JEDNEJ POZYCJI (D-1011-5 Q2, fazy w bazie): karta (wszystkie backupy pozycji ze
    wszystkich commitów przebiegu, od najnowszego - ciało `undo` per lokacja) → plik (odwrotne
    przeniesienie pod strażą; stary katalog, którego nie ma, zakładany i zapisany jako `restored`)
    → baza (CAS klingi, status `undone`). Każda faza utrwala się po sukcesie; porażka zatrzymuje TĘ
    pozycję z powodem, a ponowienie wznawia pierwszą niedomkniętą fazę."""
    lid = p["location_id"]
    faza = p["undo_phase"]

    def _stop(status, sciezka, powod):
        repo.set_object_change_undo_phase(con, item_id=p["id"], phase=None, reason=powod)
        return FileResult(lid, sciezka, status, powod)

    if p["rename_id"] is not None and p["in_flight"] is not None:
        # Zamiar renamu, którego rekoncyliacja na wejściu nie rozstrzygnęła: nie wiadomo, pod którą
        # nazwą stoi plik - ani karta, ani plik, ani baza nie ruszają się na ślepo.
        return _stop("blocked", p["old_path"], _ZAMIAR_OTWARTY)
    if faza is None:
        for b in _backupy_lokacji(con, p["run_id"], lid):
            cofniecie = _cofnij_lokacje(con, b["commit_id"], b, now=now)
            if cofniecie.wynik.status != "restored" and not cofniecie.juz:
                return _stop(cofniecie.wynik.status, cofniecie.wynik.path, PowodPozycji(
                    f"karta nie wróciła: {cofniecie.wynik.reason}", "undo_card",
                    inner=cofniecie.wynik.reason))
        repo.set_object_change_undo_phase(con, item_id=p["id"], phase="card")
        faza = "card"
    if faza == "card":
        if p["rename_id"] is not None and p["rename_status"] == "applied":
            stary = os.path.dirname(p["old_path"])
            brak = [k for k in _poziomy_pod(_wspolny_przodek(p), stary) if not os.path.isdir(k)]
            powod, zalozone = _zaloz_katalogi(con, p["run_id"], brak, now=now, akcja="restored")
            liczniki["created"] += zalozone
            if powod is not None:
                return _stop("blocked", p["new_path"], PowodPozycji(f"plik nie wrócił: {powod}",
                                                                    "undo_file", inner=powod))
            ruch = _przenies_wstecz(con, p, now=now, reason=_COFNIETO)
            if ruch.status != "applied":
                return _stop("blocked" if ruch.status == "blocked" else "failed",
                             p["old_path"] if ruch.torn else p["new_path"],
                             PowodPozycji(f"plik nie wrócił: {ruch.reason}", "undo_file",
                                          inner=ruch.reason))
        repo.set_object_change_undo_phase(con, item_id=p["id"], phase="file")
    uwaga = repo.undo_object_change_db(con, item_id=p["id"], now=now)
    teraz = _location_rename(con, lid)
    sciezka = "" if teraz is None else teraz["path"]
    # AR-82: karta wróciła do pliku, a zeznanie klatki nie - z BAZY (wstrzymanie cofnięcia związane
    # z pozycją), nie z wyniku fazy karty: wznowienie po fazie `card`/`file` go nie ma.
    wstrzymanie = repo.open_undo_withheld_for_item(con, p["id"])
    if wstrzymanie is not None:
        return FileResult(lid, sciezka, "restored", _dopisz(uwaga, wstrzymanie["reason"]),
                          code=CODE_ZEZNANIE_WSTRZYMANE)
    return FileResult(lid, sciezka, "restored", uwaga)


def undo_object_change(con, run_id, *, now,
                       progress: Callable[[int, int, str, str], None] | None = None,
                       should_cancel: Callable[[], bool] | None = None) -> ObjectChangeResult:
    """COFNIĘCIE GESTU (D-1011-5 Q2/Q3) - przebieg odtworzony z bazy, pozycje od ostatniej (jak stos):
    każda pozycja ze śladem zapisu (zapisana, częściowa, przerwana w biegu) idzie fazami karta → plik
    → baza (`_cofnij_pozycje`); pozycja, do której zapis nie doszedł, dostaje 'skipped' bez mutacji,
    a pozycja odmówiona przy zapisie (już czysta) trafia do `skipped` z powodem, bez mutacji - wynik
    cofnięcia mówi o każdej pozycji przebiegu, którą mówił zapis. Na końcu (bez anulowania) katalogi
    założone przez gest - wyłącznie z potwierdzeniem i puste.

    STATUS PRZEBIEGU: `undoing` NA WEJŚCIU (od tej chwili sterownik zapisu go nie wznowi), `undone`
    dopiero, gdy żadna pozycja nie czeka na cofnięcie, a katalogi przeszły - awaria albo pozycja
    zatrzymana z powodem zostawiają `undoing`, a ponowienie wznawia pierwszą niedomkniętą fazę każdej
    pozycji. Drugie cofnięcie domkniętego przebiegu = nic do zrobienia (pozycje `undone`, katalogi
    z `undone_at`). Na wejściu rekoncyliacja przerwanych renamów i zamiarów katalogów - jak w zapisie."""
    przebieg = _przebieg_zmiany(con, run_id)
    if przebieg is None:
        raise ValueError(f"przebieg zmiany obiektu {run_id} nie istnieje")
    if przebieg["status"] != "undone":
        repo.set_object_change_run_status(con, run_id=run_id, status="undoing")
    ostrzezenia = _ostrzezenia_rekoncyliacji(con, now=now)
    _rekoncyliuj_katalogi(con, run_id, now=now)
    pozycje = [p for p in _pozycje_przebiegu(con, run_id)
               if p["status"] in ("applied", "failed", "pending", "blocked")]
    total = len(pozycje)
    applied: list[FileResult] = []
    blocked: list[FileResult] = []
    failed: list[FileResult] = []
    skipped: list[FileResult] = []
    withheld: list[FileResult] = []
    kubly = {"restored": applied, "blocked": blocked, "failed": failed, "skipped": skipped}
    liczniki = {"created": 0}
    cancelled = False
    done = 0
    for p in reversed(pozycje):
        if should_cancel is not None and should_cancel():
            cancelled = True
            break
        if p["status"] == "blocked":
            loc = _location_rename(con, p["location_id"])
            wynik = FileResult(p["location_id"], "" if loc is None else loc["path"], "skipped",
                               PowodPozycji("odmówione przy zapisie - nic do cofnięcia",
                                            "undo_refused_earlier"))
        elif p["status"] == "pending" and _bez_sladu(con, p):
            wynik = _wycofaj_pozycje(con, p, "skipped", PowodPozycji(
                "przebieg cofnięty, zanim zapis doszedł do tej pozycji", "undo_before_write"),
                now=now, przeniesiony=False)
        else:
            wynik = _cofnij_pozycje(con, p, now=now, liczniki=liczniki)
        kubly[wynik.status].append(wynik)
        if wynik.code == CODE_ZEZNANIE_WSTRZYMANE:
            withheld.append(wynik)
        done += 1
        if progress is not None:
            progress(done, total, wynik.path, wynik.status)
    usuniete = 0
    if not cancelled:
        usuniete, niepuste = _usun_wlasne_puste(con, run_id, now=now)
        ostrzezenia.extend(ZdanieRdzenia(f"katalog {k}: założony przez gest, ale nie jest pusty - "
                                         f"zostaje", "dir_not_empty", dir=k) for k in niepuste)
        if not any(p["status"] in ("applied", "failed", "pending")
                   for p in _pozycje_przebiegu(con, run_id)):
            # Status `undone` i nagrobek obiektu, który gest założył (AR-137, `Q8`) - jedna
            # transakcja klingi; odmowa nagrobka (obiekt ma klatki, obcy alias) to zwykły stan.
            repo.close_object_change_undo(con, run_id=run_id, now=now)
    niepewne = _niepewne_katalogi(con, run_id)
    ostrzezenia.extend(_uwaga_niepewnej_wlasnosci(k) for k in niepewne)
    return ObjectChangeResult(run_id, applied, blocked, failed, skipped,
                              _commity_przebiegu(con, run_id), liczniki["created"], usuniete,
                              len(niepewne), cancelled, tuple(ostrzezenia), withheld=withheld)

