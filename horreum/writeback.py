"""DRUGA KLINGA — jedyny obramkowany dom MUTACJI PLIKÓW (KROK 4 scalenia, brief PLAN_gui_writeback).

Odpowiednik `repo.py` dla plików: writeback nagłówków FITS to JEDYNY sankcjonowany zapis na dysk
usera (poza nim pliki = zimny magazyn, `safety.py`). Statyczny meta-tripwir AST
(`tests/test_writeback_safety.py`) pilnuje, że `os.replace`/`writeto`/`tempfile`/`os.remove` żyją
WYŁĄCZNIE tutaj (wzorzec `mover.py`/`eraser.py` Custosa, przełożony z zakazu DML poza `repo.py`).

Dwie warstwy:
1. WRITER (port dawcy `fits_io.write_changes`/`write_full_header`): atomowy zapis nagłówka —
   plik tymczasowy w tym samym katalogu + `os.replace` (atomowo na wolumenie). Kontrola
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
import shutil
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

from . import exif, repo, scan

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
    w bazie, a zapis mógł ruszyć bajty"."""
    status: str            # 'applied' | 'blocked' | 'failed'
    reason: str | None
    post_hash: str | None  # header_hash PO zapisie (z ZAPISANEGO pliku) — kontrola undo + kolejny zapis
    backup_text: str | None = None  # pełny nagłówek SPRZED zapisu (undo)
    in_place: bool = False


# ============================================================ REGUŁY KARTY (jeden właściciel)
# Treść, którą ŁATA wnosi do nagłówka, spełnia reguły karty FITS 4.0 (§4.1-4.2) - w OBU formatach:
# XISF przejmuje je wprost (spec XISF 1.0 Rev. 1 §11.6: dane `<FITSKeyword>` spełniają wymagania
# FITS 4.0 dla kart). Właściciel jest JEDEN - `card_violation`: woła go pisarz FITS, pisarz XISF
# i dialog naprawy nagłówka (`gui/app.py`), który pyta go przed stagingiem, żeby odmowa padła
# wcześniej, a nie inną regułą.
#
# Dlaczego tu, a nie w astropy czy w czytniku - zmierzone na astropy 8.0.0: znak sterujący
# i nie-ASCII odrzuca już przypisanie karty, ale angielskim `ValueError`, czyli dawniej 'failed'
# („coś się zepsuło") zamiast odmowy; wartość dłuższa niż rekord przechodzi po cichu jako CONTINUE,
# za długi komentarz jest po cichu UCINANY, a zła nazwa przy `add` zakłada kartę HIERARCH. Przy XISF
# nie odmawiał nikt: znak sterujący szedł do nagłówka surowo, a nagłówek przestawał być poprawnym
# XML 1.0 (spec §9.5 - PixInsight takiego pliku nie otworzy). Czytnik Horreum ten znak neutralizuje
# (`scan.xml_parsable`), więc odczyt po zapisie tego nie widział.
#
# Reguły pilnują TREŚCI ŁATY, nie pliku: zastana nielegalna treść (w archiwum jest plik z bajtem
# 0x07 w historii przetwarzania) nie blokuje łaty legalnej wartości. Nazwę sprawdzamy tylko wtedy,
# gdy łata ją WNOSI (nowa karta) - `set` na istniejącej karcie jej nazwy nie zmienia.

_FITS_NAME = re.compile(r"[A-Z0-9_-]{1,8}")   # §4.1.2.1: do 8 znaków z tego zbioru
FITS_STRING_MAX = 68      # tekst w apostrofach w JEDNYM rekordzie: 80 - nazwa 8 - "= " 2 - apostrofy 2
_FITS_RECORD = 80
_FITS_VALUE_START = 10    # nazwa (8) + wskaźnik wartości "= " (2)
_FITS_FIXED_FIELD = 20    # stały format (§4.2): pole wartości zajmuje co najmniej kolumny 11-30
_FITS_COMMENT_SEP = 3     # " / "


@dataclasses.dataclass(frozen=True)
class CardViolation:
    """Naruszenie reguł karty wniesione przez łatę. `reason` idzie do raportu pisarza; `kind`
    ('name' | 'chars' | 'length') oraz `length`/`limit` służą powierzchniom, które mówią własnym
    językiem (i18n dialogu naprawy nagłówka)."""
    kind: str
    reason: str
    length: int | None = None
    limit: int | None = None


def _first_illegal(text):
    """Pierwszy znak spoza drukowalnego ASCII (0x20-0x7E) albo `None`. FITS 4.0 dopuszcza w wartości
    tekstowej (§4.2.1.1) i w komentarzu (§4.1.2.3) wyłącznie ten zbiór; XML 1.0 jest od niego
    szerszy, więc zbiór FITS domyka też legalność nagłówka XISF."""
    return next((ch for ch in text if not " " <= ch <= "~"), None)


def card_violation(keyword, value, comment=None, *, new_card=False) -> CardViolation | None:
    """Czy karta `keyword = value / comment` łamie reguły FITS 4.0 → `CardViolation` albo `None`.

    Trzy reguły, w tej kolejności:
    1. **Nazwa** (tylko `new_card=True`, bo tylko nowa karta wnosi nazwę): po `strip().upper()` -
       tak ją zapisują oba pisarze - do 8 znaków `A-Z 0-9 _ -`.
    2. **Znaki** wartości i komentarza: drukowalne ASCII 0x20-0x7E. Znak sterujący w XISF łamie też
       XML 1.0, i to bez ratunku: nie ma go jak zakodować (`scan._escape_xml`).
    3. **Długość** - karta mieści się w JEDNYM rekordzie 80 znaków. Wartość liczona jak tekst
       w apostrofach z podwojonym apostrofem wewnątrz (tak ją zapisuje FITS i `scan.quote_fits`),
       limit `FITS_STRING_MAX`; dla liczby limit jest o dwa znaki luźniejszy, a liczba tej długości
       nie istnieje, więc reguła jest jedna. Dłuższa wartość wymagałaby kontynuacji CONTINUE (astropy
       robi ją po cichu), a XISF-owy `<FITSKeyword>` nie ma rekordów, na które mógłby się rozpaść.
       Komentarz mieści się w reszcie rekordu po ` / ` przy polu wartości STAŁEGO formatu
       (co najmniej 20 znaków) - tak kartę układa astropy, więc dla FITS reguła jest dokładna
       (poza nią astropy ucina komentarz po cichu), a dla XISF ostrożna. Liczymy komentarz
       WNOSZONY przez łatę; zastany komentarz karty przy `set` bez komentarza zostaje poza regułą
       (XISF go nie rusza, a FITS przy zmianie wartości układa kartę od nowa i potrafi go uciąć -
       to osobny dług pisarza FITS, nie reguła treści łaty).

    Wartość sprawdzamy w postaci TEKSTOWEJ (`str(value)`) - dokładnie tej, która stoi w stagingu
    i którą pisarz XISF wstawia do pliku."""
    name = str(keyword).strip().upper()
    comment = None if comment is None else str(comment)
    if new_card and not _FITS_NAME.fullmatch(name):
        return CardViolation(
            "name", f"nazwa karty {name!r} łamie reguły FITS 4.0 - do 8 znaków spośród A-Z, 0-9, "
                    f"'_' i '-'")
    text = str(value)
    for pole, tresc in (("wartość", text), ("komentarz", comment)):
        znak = _first_illegal(tresc) if tresc is not None else None
        if znak is not None:
            return CardViolation(
                "chars", f"{pole} karty {name} ma znak {znak!r} spoza drukowalnego ASCII - karta "
                         f"FITS go nie przyjmie, a w nagłówku XISF łamie XML 1.0")
    pole_wartosci = len(text.replace("'", "''"))
    if pole_wartosci > FITS_STRING_MAX:
        return CardViolation(
            "length", f"wartość karty {name} ma {pole_wartosci} znaków, a jeden rekord FITS mieści "
                      f"{FITS_STRING_MAX}", length=pole_wartosci, limit=FITS_STRING_MAX)
    if comment:
        limit = (_FITS_RECORD - _FITS_VALUE_START - _FITS_COMMENT_SEP
                 - max(pole_wartosci + 2, _FITS_FIXED_FIELD))
        if len(comment) > limit:
            return CardViolation(
                "length", f"komentarz karty {name} ma {len(comment)} znaków, a przy tej wartości "
                          f"rekord FITS mieści {max(limit, 0)}", length=len(comment),
                limit=max(limit, 0))
    return None


def _ops_violation(ops, is_new: Callable[[WriteOp], bool]) -> str | None:
    """Powód pierwszego naruszenia reguł karty w komplecie operacji albo `None`. Czy operacja
    ZAKŁADA kartę (`is_new`), wie tylko pisarz danego formatu: FITS `set` na nieobecnej karcie
    dopisuje ją po cichu (astropy), XISF odmawia."""
    for op in ops:
        naruszenie = card_violation(op.keyword, op.value, op.comment, new_card=is_new(op))
        if naruszenie is not None:
            return naruszenie.reason
    return None


def _after_replace(path: str, written_hash: str, backup_text: str) -> WriteResult:
    """Weryfikacja PO `os.replace` - wspólna dla FITS i XISF. Plik JEST już podmieniony, więc KAŻDY
    wynik stąd niesie `backup_text`: 'failed' bez backupu zostawiłby zapisany plik bez drogi powrotu.

    `written_hash` = hash nagłówka, który pisarz ZAPISAŁ (XISF: sha1 złożonego XML-a; FITS: odczyt
    pliku tymczasowego przed podmianą). Odczyt po zapisie (T3) musi dać dokładnie ten hash - te same
    bajty, ta sama formuła. Rozjazd albo nieudany odczyt → 'failed' z `post_hash=written_hash`:
    undo porównuje dysk z tym hashem, więc cofnie wyłącznie plik, na którym leży to, co zapisaliśmy,
    a plik zmieniony w międzyczasie przez kogoś innego zostawi jako 'blocked'."""
    try:
        post = _post_hash(path)
    except Exception as exc:  # noqa: BLE001 - raport zamiast wyjątku w warstwie zapisu
        return WriteResult("failed", f"plik PODMIENIONY, ale odczyt po zapisie padł - "
                                     f"{type(exc).__name__}: {exc}", written_hash, backup_text)
    if post != written_hash:
        return WriteResult("failed", "plik PODMIENIONY, ale odczyt po zapisie pokazuje inny nagłówek "
                                     "niż zapisany", written_hash, backup_text)
    return WriteResult("applied", None, post, backup_text)


def _podmien(tmp: str, path: str, replace_guard) -> None:
    """`os.replace(tmp, path)` - pod strażą podmiany, gdy wołający ją podał (`replace_guard()` =
    menedżer kontekstu, orkiestracja podaje `repo.guard_file_replace`). Straż sprawdza stan bazy
    i trzyma jej blokadę zapisu przez samą podmianę; odmowa (`repo.InplaceConflict`) wychodzi
    PRZED `os.replace`, więc plik zostaje nietknięty. Błąd przy ZAMKNIĘCIU straży już po podmianie
    nie cofa podmiany i nie może udawać, że jej nie było - jest połykany (straż niczego nie pisze,
    więc jej zatwierdzenie nie niesie faktu), a o wyniku mówi weryfikacja po podmianie."""
    if replace_guard is None:
        os.replace(tmp, path)
        return
    straz = replace_guard()
    straz.__enter__()
    try:
        os.replace(tmp, path)
    except BaseException:
        if not straz.__exit__(*sys.exc_info()):
            raise
        return
    try:
        straz.__exit__(None, None, None)
    except Exception:  # noqa: BLE001 - podmiana już zaszła (docstring)
        pass


def _coerce(value, value_type: str):
    if value_type == "int":
        return int(value)
    if value_type == "float":
        return float(value)
    if value_type == "bool":
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("t", "true", "1", "yes")
    return str(value)


def _count_keyword(hdr, keyword: str) -> int:
    return sum(1 for c in hdr.cards if c.keyword == keyword)


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
    raise KeyError(f"{keyword}[{n}] nie istnieje w naglowku")


def _apply_op(hdr, op: WriteOp) -> None:
    value = _coerce(op.value, op.value_type)
    if op.op == "add":
        # Jawne dodanie BRAKUJACEGO keyworda (astropy dopisuje na koniec). Obrona przed wyscigiem:
        # gdy keyword juz jest, `add` nie nadpisuje cicho (to robi `set`).
        if _count_keyword(hdr, op.keyword) > 0:
            raise ValueError(f"add: keyword '{op.keyword}' juz istnieje (uzyj set)")
        hdr[op.keyword] = (value, op.comment) if op.comment is not None else value
        return
    if op.op == "set":
        if (op.idx in (None, 0)) and _count_keyword(hdr, op.keyword) <= 1:
            hdr[op.keyword] = (value, op.comment) if op.comment is not None else value
        else:
            _set_nth(hdr, op.keyword, op.idx or 0, value, op.comment)
        return
    raise ValueError(f"nieznana operacja: {op.op!r}")


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
                  persist_backup: Callable[[str, str], None] | None = None,
                  replace_guard=None) -> WriteResult:
    """Atomowo zapisz zmiany w nagłówku wybranego HDU. Kontrola `header_hash`: nagłówek na dysku ≠
    `expected_hash` → 'blocked', NIE pisze. Treść łamiąca reguły karty FITS 4.0 (`card_violation`)
    → 'blocked' z powodem, NIE pisze - zamiast angielskiego wyjątku astropy albo cichego CONTINUE,
    ucięcia komentarza czy karty HIERARCH. Plik tymczasowy jest czytany PRZED podmianą (plik
    nieczytelny nie zastąpi oryginału), a jego hash jest kotwicą weryfikacji po podmianie
    (`_after_replace`). Zwraca `post_hash` z zapisanego pliku + `backup_text` - także przy 'failed'
    PO podmianie. Port dawcy `fits_io.write_changes`.
    `.xisf` → `write_xisf_changes` (inny format, TEN SAM kontrakt `WriteResult`).
    `.dng/.arw/.cr2` → ODMOWA (#2): RAW jest read-only (rename dozwolony osobno).

    BACKUP PRZED PODMIANĄ (Z3, 2026-09-26): `backup_text` = `RegionBackup` (surowy region nagłówka
    sprzed zmian + metadane), a `persist_backup(backup_text, post_hash)` - gdy podany - utrwala go
    w bazie PRZED `os.replace`. Porażka backupu → 'failed', oryginał nietknięty, plik tymczasowy
    sprzątnięty. Dawniej backup powstawał PO podmianie, więc jego porażka zostawiała plik zmieniony
    bez drogi powrotu.

    STRAŻ PODMIANY (`replace_guard`, astra 2026-09-27): `os.replace` idzie pod menedżerem kontekstu
    wołającego (`_podmien`) - orkiestracja podaje `repo.guard_file_replace`, która w transakcji
    zapisu bazy sprawdza, że od bramki izolacji nikt nie zaczął na tej lokacji zapisu w miejscu.
    Odmowa (`repo.InplaceConflict`) → 'blocked' z powodem, plik nietknięty, plik tymczasowy
    sprzątnięty; backup został utrwalony wcześniej i zostaje (append-only, nigdy nie wskaże bajtów,
    których nie było - undo takiego backupu rozpozna nagłówek inny niż `post_hash`)."""
    if _is_raw(path):
        return WriteResult("blocked", "format RAW jest read-only (#2)", None)
    if _is_xisf(path):
        return write_xisf_changes(path, ops, expected_hash, persist_backup=persist_backup,
                                  replace_guard=replace_guard)
    path = os.fspath(path)
    tmp: str | None = None
    try:
        with fits.open(path, mode="readonly", memmap=False) as hdul:
            index, hdu = scan._select_hdu(hdul)
            hdr = hdu.header
            current = scan._header_hash(hdr)
            if expected_hash is not None and current != expected_hash:
                return WriteResult("blocked", "header_hash mismatch", None)
            # Nowa karta = `add` ALBO `set` na karcie nieobecnej - tę `_apply_op` dopisuje po
            # cichu (semantyka astropy), więc jej nazwa też jest treścią wniesioną przez łatę.
            powod = _ops_violation(
                ops, lambda op: op.op == "add" or _count_keyword(hdr, op.keyword) == 0)
            if powod is not None:
                return WriteResult("blocked", powod, None)
            info = hdul.fileinfo(index)
            start, data_start = info["hdrLoc"], info["datLoc"]
            for op in ops:
                _apply_op(hdr, op)
            fd, tmp = tempfile.mkstemp(suffix=".tmp", dir=os.path.dirname(os.path.abspath(path)))
            os.close(fd)
            hdul.writeto(tmp, overwrite=True)
        # Poza `with`: uchwyt oryginału zwolniony (Windows). Odczyt pliku tymczasowego TĄ SAMĄ
        # formułą co skan, zanim zastąpi oryginał: nieczytelny → 'failed' i oryginał nietknięty;
        # czytelny → hash tego, co za chwilę będzie na dysku (kotwica `_after_replace`).
        written_hash = scan.read_fits_meta(tmp).header_hash
        backup_text = _region_backup(path, "fits", start, data_start - start, current).encode()
        if persist_backup is not None:
            try:
                persist_backup(backup_text, written_hash)
            except Exception as exc:  # noqa: BLE001 - bez backupu nie podmieniamy
                return WriteResult("failed", f"backup do cofnięcia NIE powstał, więc podmiany nie "
                                             f"było - plik nietknięty: {type(exc).__name__}: {exc}",
                                   None)
        _podmien(tmp, path, replace_guard)                 # os.replace (pod strażą wołającego)
        tmp = None
    except repo.InplaceConflict as exc:                    # straż odbiła podmianę - plik nietknięty
        return WriteResult("blocked", _powod_konfliktu(exc.op), None)
    except Exception as exc:  # noqa: BLE001 - raport zamiast wyjątku w warstwie zapisu
        return WriteResult("failed", f"{type(exc).__name__}: {exc}", None)
    finally:
        if tmp is not None and os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
    return _after_replace(path, written_hash, backup_text)   # T3: hash z ZAPISANEGO pliku


def write_full_header(path, header_text: str, expected_hash: str | None, *,
                      replace_guard=None) -> WriteResult:
    """Atomowo przywróć nagłówek z backupu (ścieżka undo): plik tymczasowy + `os.replace`. Kontrola
    `header_hash` jak w `write_changes` (dysk ≠ `expected_hash` → 'blocked'). `header_text` = backup
    dowolnej generacji: koperta `RegionBackup` (od 2026-09-26) albo tekst sprzed niej
    (`hdr.tostring()` dla FITS, XML dla XISF). Dane nietknięte (`sha1_data` zostaje).
    `.dng/.arw/.cr2` → ODMOWA (#2).

    Cofnięcie W MIEJSCU to osobna droga (`restore_inplace`) - wyłącznie dla commitu zapisanego
    w miejscu, z operacją w dzienniku `inplace_op` (astra Z12): tylko wtedy przerwane cofnięcie ma
    materiał odzysku. Stare backupy tekstowe i commity atomowe cofają się tu, atomowo.
    `replace_guard` = straż podmiany jak w `write_changes` (odmowa → 'blocked', plik nietknięty)."""
    if _is_raw(path):
        return WriteResult("blocked", "format RAW jest read-only (#2)", None)
    path = os.fspath(path)
    tekst = _backup_header_text(header_text)
    if _is_xisf(path):
        return _xisf_full_header_atomic(path, tekst, expected_hash, header_text,
                                        replace_guard=replace_guard)
    tmp: str | None = None
    try:
        with fits.open(path, mode="readonly", memmap=False) as hdul:
            index, hdu = scan._select_hdu(hdul)
            current = scan._header_hash(hdu.header)
            if expected_hash is not None and current != expected_hash:
                return WriteResult("blocked", "header_hash mismatch", None)
            hdu.header = fits.Header.fromstring(tekst)
            fd, tmp = tempfile.mkstemp(suffix=".tmp", dir=os.path.dirname(os.path.abspath(path)))
            os.close(fd)
            hdul.writeto(tmp, overwrite=True)
        _podmien(tmp, path, replace_guard)                 # os.replace (pod strażą wołającego)
        tmp = None
        post = _post_hash(path)
    except repo.InplaceConflict as exc:
        return WriteResult("blocked", _powod_konfliktu(exc.op), None)
    except Exception as exc:  # noqa: BLE001
        return WriteResult("failed", f"{type(exc).__name__}: {exc}", None)
    finally:
        if tmp is not None and os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
    return WriteResult("applied", None, post, header_text)


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
    „nie ruszam, bo nie rozumiem" nigdy nie zlało się z „coś się zepsuło" (to drugie = 'failed')."""

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
    except Exception as exc:  # noqa: BLE001 — czytnik zgłasza format wieloma typami (w tym ParseError)
        raise _XisfRefusal(f"nagłówek XISF nieczytelny — {type(exc).__name__}: {exc}") from exc


def _xisf_gates(meta) -> None:
    """Bramki odmowy liczone z PLIKU (D-X-11/13), zanim cokolwiek policzymy z operacji.

    Bramka tożsamości ma bliźniaka w bazie (`macro.resolve_target` czyta
    `frame.sha1_data_uncomputable`) — ta tutaj domyka wywołanie pisarza z pominięciem makra."""
    if meta.keyword_images > 1:
        raise _XisfRefusal("karty pod wieloma <Image> — cel zapisu niejednoznaczny (D-X-11)")
    if meta.image_span is None:
        raise _XisfRefusal("tożsamość nieobliczalna (brak obrazu-attachmentu) — "
                           "zapis rozdwoiłby klatkę (D-X-13)")


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
        raise _XisfRefusal(str(exc)) from exc
    obecna = xml[span[0]:span[1]]
    stara_karta = next((c.value_raw for c in meta.cards
                        if c.keyword == keyword and c.idx == idx), None)
    if stara_karta is None:                            # lustro kart rozjechane z lokalizatorem
        raise ValueError(f"XISF: karta {keyword}[{idx}] zlokalizowana, ale nieobecna w lustrze kart")
    try:
        z_karty = scan.encode_xisf_value(rule(stara_karta), xml, span)
        nowa = scan.encode_xisf_value(rule(new_text), xml, span)
    except (TypeError, ValueError) as exc:
        raise _XisfRefusal(f"własność {pid}: reguła nie liczy się dla {new_text!r} "
                           f"({type(exc).__name__}: {exc})") from exc
    if z_karty != obecna:
        raise _XisfRefusal(
            f"własność {pid} = {obecna.decode('utf-8', 'replace')}, a z karty {keyword}="
            f"{stara_karta!r} wychodzi {z_karty.decode('utf-8', 'replace')} — konwencji tego pliku "
            f"NIE ROZUMIEM, więc jej nie ruszam")
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
        raise _XisfRefusal(f"karta {keyword} już istnieje — 'add' dopisałby drugą; zmiana wartości "
                           f"idzie przez 'set'")
    target = _XISF_PROPERTY_TARGETS.get(keyword)
    if target is not None:
        try:
            scan.locate_value_span(xml, property_id=target[0])
        except scan.XisfTargetMissing:
            pass
        except scan.XisfValueUnreachable as exc:
            raise _XisfRefusal(str(exc)) from exc
        else:
            raise _XisfRefusal(
                f"plik nie ma karty {keyword}, ale ma własność {target[0]} — dopisanie karty "
                f"mogłoby mu zaprzeczyć, a bramki zrozumienia nie ma na czym postawić")
    try:
        offset, blob = scan.build_fits_keyword_element(
            xml, keyword=keyword, value=new_text, comment=comment)
    except ValueError as exc:                 # w tym XisfTargetMissing/Unreachable (podklasy)
        raise _XisfRefusal(str(exc)) from exc
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
            raise _XisfRefusal(f"operacja '{op.op}' na XISF nie istnieje — writeback zna 'set' "
                               f"i 'add'")
        keyword, idx = op.keyword.strip().upper(), op.idx or 0
        new_text = str(op.value)
        if op.op == "add":
            patches.append(_xisf_add_patch(meta, keyword, new_text, op.comment))
            continue
        try:
            span = scan.locate_value_span(xml, keyword=keyword, idx=idx)
        except scan.XisfTargetMissing as exc:
            raise _XisfRefusal(f"{exc} — 'set' nie zakłada karty; dopisanie idzie przez "
                               f"'add' (P6d)") from exc
        patches.append((*span, scan.quote_fits(new_text, xml[span[0]:span[1]])))
        if op.comment is not None:
            try:
                cspan = scan.locate_value_span(xml, keyword=keyword, idx=idx, attr="comment")
            except scan.XisfTargetMissing as exc:
                raise _XisfRefusal(f"{exc} — dodanie atrybutu poza P6 (D-X-12)") from exc
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
        raise _XisfRefusal(f"nagłówek nie jest tekstem UTF-8 — backup do undo niemożliwy ({exc})")
    if text.encode("utf-8") != meta.xml_bytes:
        raise _XisfRefusal("nagłówek nie przechodzi round-tripu bajty→tekst→bajty — "
                           "backup do undo byłby nieodwracalny")
    return text


def _write_xisf_file(path: str, region: bytes, tail_start: int, replace_guard=None) -> None:
    """Atomowa podmiana pliku XISF: temp w TYM SAMYM katalogu (ten sam wolumen → `os.replace` jest
    atomowy), nowy region nagłówka + OGON verbatim od pierwszego bloku danych. Kopiujemy cały plik
    - parytet z FITS, gdzie `hdul.writeto(tmp)` robi dokładnie to samo. Łata w miejscu (`r+b`) była
    tu odrzucona jako NIEATOMOWA; od O5 (2026-09-26) istnieje obok jako osobna droga z backupem
    PRZED zapisem (sekcja „ZAPIS W MIEJSCU"), a ta zostaje drogą `commit(inplace=False)`.
    `replace_guard` = straż podmiany (`_podmien`); jej odmowa (`repo.InplaceConflict`) wychodzi
    przed `os.replace`, a plik tymczasowy sprząta `finally`."""
    tmp: str | None = None
    try:
        fd, tmp = tempfile.mkstemp(suffix=".tmp", dir=os.path.dirname(os.path.abspath(path)))
        os.close(fd)
        with open(path, "rb") as src, open(tmp, "wb") as dst:
            dst.write(region)
            src.seek(tail_start)
            shutil.copyfileobj(src, dst, 1 << 20)
        _podmien(tmp, path, replace_guard)   # poza `with`: uchwyty zwolnione (Windows) → podmiana
        tmp = None
    finally:
        if tmp is not None and os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


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


def _xisf_prepare(path: str, ops: list[WriteOp], expected_hash: str | None):
    """Wszystko, co pisarz XISF liczy PRZED dotknięciem pliku, wspólne dla drogi atomowej
    (`write_xisf_changes`) i zapisu w miejscu (`_xisf_inplace_plan`) - jedna kolejność bramek,
    więc obie drogi odmawiają tych samych plików tymi samymi słowami.

    Zwraca `(meta, new_xml, backup_text, region)`; odmowa to `_XisfRefusal` (w tym niezgodny
    `header_hash` - powód „header_hash mismatch", jak w FITS), awaria - każdy inny wyjątek."""
    meta = _read_xisf_or_refuse(path)
    if expected_hash is not None and meta.header_hash != expected_hash:
        raise _XisfRefusal("header_hash mismatch")
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
        raise _XisfRefusal(str(exc)) from exc
    return meta, new_xml, backup_text, region


def write_xisf_changes(path, ops: list[WriteOp], expected_hash: str | None, *,
                       persist_backup: Callable[[str, str], None] | None = None,
                       replace_guard=None) -> WriteResult:
    """Łata bajtowa nagłówka XISF - bliźniak `write_changes` z tym samym kontraktem `WriteResult`.

    Kolejność (brief §5, `_xisf_prepare`): odczyt → kontrola `header_hash` (≠ → 'blocked', NIE
    pisze) → bramki D-X-11/13 → REGUŁY KARTY (`card_violation`, spec §11.6) → lokalizacja
    i podmiana wycinków (karta + zmapowana własność + komentarz) → WERYFIKACJA nowego XML-a
    (`_xisf_verify`: §9.5 i round-trip kart) → round-trip backupu (D-X-9) → BRAMKA MIESZCZENIA SIĘ
    (D-X-2) → backup (`RegionBackup` całego regionu `[0, first_attachment)`, utrwalony przez
    `persist_backup` PRZED podmianą - Z3) → temp + `os.replace` → weryfikacja po podmianie
    (`_after_replace`: `post_hash` z ZAPISANEGO pliku == sha1 złożonego XML-a).

    Odmowa ('blocked') zostawia plik bajtowo nietknięty - wszystkie bramki liczą się PRZED
    stworzeniem pliku tymczasowego. Awaria ('failed') to każdy inny wyjątek, w tym rozejście się
    skanu bajtowego z parserem (guard `locate_value_span`) i nieudana weryfikacja nowego XML-a: tam
    nie wiemy, co byśmy zapisali, więc nie piszemy, ale to usterka do zbadania, nie polityka odmowy."""
    path = os.fspath(path)
    try:
        meta, new_xml, _, region = _xisf_prepare(path, ops, expected_hash)
        backup_text = _region_backup(path, "xisf", 0, meta.first_attachment,
                                     meta.header_hash).encode()
        # Header_hash XISF to sha1 bajtów XML (D-X-3), a pisarz zapisuje je 1:1 - więc hash tego,
        # co zapiszemy, znamy bez odczytu, a odczyt (T3) ma go tylko potwierdzić.
        written_hash = hashlib.sha1(new_xml).hexdigest()
        if persist_backup is not None:
            try:
                persist_backup(backup_text, written_hash)
            except Exception as exc:  # noqa: BLE001 - bez backupu nie podmieniamy
                return WriteResult("failed", f"backup do cofnięcia NIE powstał, więc podmiany nie "
                                             f"było - plik nietknięty: {type(exc).__name__}: {exc}",
                                   None)
        _write_xisf_file(path, region, meta.first_attachment,           # tu następuje os.replace
                         replace_guard)
    except _XisfRefusal as ref:
        return WriteResult("blocked", ref.reason, None)
    except repo.InplaceConflict as exc:                    # straż odbiła podmianę - plik nietknięty
        return WriteResult("blocked", _powod_konfliktu(exc.op), None)
    except Exception as exc:  # noqa: BLE001 - raport zamiast wyjątku w warstwie zapisu
        return WriteResult("failed", f"{type(exc).__name__}: {exc}", None)
    return _after_replace(path, written_hash, backup_text)


def write_xisf_full_header(path, header_text: str, expected_hash: str | None) -> WriteResult:
    """Przywróć nagłówek XISF z backupu (ścieżka undo, D-X-9) - to samo co `write_full_header`
    dla pliku `.xisf` (najpierw w miejscu pod blokadą, zob. tam). Nazwa zostaje dla wołających."""
    return write_full_header(path, header_text, expected_hash)


def _xisf_full_header_atomic(path: str, xml_text: str, expected_hash: str | None,
                             backup_text: str, *, replace_guard=None) -> WriteResult:
    """Droga atomowa przywrócenia XISF (plik tymczasowy + `os.replace`) - spadek, gdy koperta
    regionu nie pasuje do bieżących adresów bloków. Ta sama bramka mieszczenia się co zapis;
    wypełnienie po skróceniu wraca jako ZERA. `replace_guard` = straż podmiany (`_podmien`)."""
    try:
        meta = _read_xisf_or_refuse(path)
        if expected_hash is not None and meta.header_hash != expected_hash:
            return WriteResult("blocked", "header_hash mismatch", None)
        try:
            region = scan.build_xisf_header_region(meta, xml_text.encode("utf-8"))
        except ValueError as exc:
            raise _XisfRefusal(str(exc)) from exc
        _write_xisf_file(path, region, meta.first_attachment, replace_guard)
        post = _post_hash(path)
    except _XisfRefusal as ref:
        return WriteResult("blocked", ref.reason, None)
    except repo.InplaceConflict as exc:
        return WriteResult("blocked", _powod_konfliktu(exc.op), None)
    except Exception as exc:  # noqa: BLE001
        return WriteResult("failed", f"{type(exc).__name__}: {exc}", None)
    return WriteResult("applied", None, post, backup_text)


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
# FITS, gdy łata nie mieści się w tym samym 80-bajtowym rekordzie z zastanym komentarzem, gdy
# karta występuje więcej niż raz, gdy operacja to `add` albo wartość nietekstowa. FITS z kartą
# `CHECKSUM`/`DATASUM` to ODMOWA ('blocked'), nie spadek: zapis w miejscu unieważniłby sumę, a obie
# drogi jej dziś nie przeliczają. XISF spadku NIE MA: region nagłówka XISF ma stały rozmiar w obu
# drogach, więc brak rezerwy odmawia tak samo tu, jak w pliku tymczasowym.

_PROBE_BYTES = 1 << 16    # próbka: przed regionem, początek danych, koniec pliku (po 64 KiB)
# Karty układu danych FITS (+ `NAXISn`): przywrócenie w miejscu wymaga, żeby były TE SAME - inaczej
# te same bajty danych znaczyłyby co innego. Zapis w miejscu ich nie łata w ogóle (tylko wartości
# tekstowe), więc dla commitu to asercja, a dla undo - bramka.
_FITS_LAYOUT_KEYWORDS = frozenset({"SIMPLE", "XTENSION", "BITPIX", "NAXIS", "EXTEND", "PCOUNT",
                                   "GCOUNT", "GROUPS", "BZERO", "BSCALE", "BLANK"})
# Karty bez wartości albo z wartością, której układ nie jest „keyword = 'tekst' / komentarz".
_FITS_NOT_INPLACE = frozenset({"", "COMMENT", "HISTORY", "CONTINUE", "END"})
# Sumy kontrolne FITS (standard 4.0, dodatek J): zmiana bajtu nagłówka unieważnia CHECKSUM.
_FITS_SUM_KEYWORDS = ("CHECKSUM", "DATASUM")
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
    gdy `location.file_sha1` jest pusty."""
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


def _backup_header_text(backup_text: str) -> str:
    """Tekst nagłówka z backupu dowolnej generacji (koperta regionu albo tekst sprzed 2026-09-26)."""
    env = RegionBackup.decode(backup_text)
    return env.header_text() if env is not None else backup_text


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


def _sha1_z_podstawieniem(path: str, offset: int, region: bytes) -> str:
    """sha1 pliku, w którym bajty `[offset, offset+len(region))` zastąpiono `region` - czyli sha1
    pliku SPRZED operacji, o ile operacja zmieniła wyłącznie swój region. Porównany z kotwicą bazy
    (`location.file_sha1` sprzed zapisu) dowodzi, że żaden bajt POZA regionem nagłówka się nie
    zmienił - także drugie HDU FITS i kolejne obrazy/załączniki XISF, których nie widzą ani próbki,
    ani `sha1_data`.

    Osobny pełny odczyt (poza strumieniem `scan.scan_file`): jedyny strumień, który i tak czyta cały
    plik, żyje w `hashing.sha1_of_span`, poza klingą. Wołane pod blokadą pliku, więc oba odczyty
    widzą te same bajty."""
    h = hashlib.sha1()
    koniec = offset + len(region)
    pos = 0
    with open(path, "rb") as f:
        while True:
            b = f.read(_SHA1_BUF)
            if not b:
                break
            a, e = max(offset, pos), min(koniec, pos + len(b))
            if a < e:
                b = b[:a - pos] + region[a - offset:e - offset] + b[e - pos:]
            h.update(b)
            pos += len(b)
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
    operacji (`old_region` od `offset`) == `anchor_sha1` (kotwica sprzed zapisu)."""
    offset: int
    old_region: bytes
    anchor_sha1: str | None
    header_hash: str


def _region_backup(path: str, fmt: str, offset: int, length: int, pre_hash: str) -> RegionBackup:
    """`RegionBackup` z pliku przez zwykły uchwyt odczytu (droga atomowa)."""
    with open(path, "rb") as fh:
        st = os.fstat(fh.fileno())
        fh.seek(offset)
        region = fh.read(length)
        if len(region) != length:
            raise ValueError(f"region {offset}:{offset + length} niekompletny ({len(region)} B)")
        return RegionBackup(fmt, offset, region, st.st_size, st.st_ino, pre_hash)


@contextlib.contextmanager
def _exclusive(path: str):
    """Uchwyt `r+b` z BLOKADĄ ZAPISU INNYCH (krok 0 sekcji): `CreateFileW(GENERIC_READ |
    GENERIC_WRITE, FILE_SHARE_READ, OPEN_EXISTING)`. Zmierzone 2026-09-26: na NTFS (tmp) i na
    udziale SMB (`R:\\_test_blokady`, poza archiwum) przy trzymanym uchwycie zapis z INNEGO procesu,
    drugie otwarcie do zapisu, usunięcie i `os.replace` na ten plik → odmowa; odczyt osobnym
    uchwytem i zapis własnym działają; `st_ino` stabilny (niezerowy) między otwarciami i po zapisie.
    Niezmierzone: drugi komputer.
    Błąd współdzielenia/blokady przy otwarciu → ponów z przerwami `_LOCK_RETRY_DELAYS`, potem
    `OSError` (zapis się nie zaczął). Poza Windows → `OSError` (zapis w miejscu niedostępny).

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
            raise ctypes.WinError(err)
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
        return WriteResult("blocked", "header_hash mismatch", None)
    if _fits_layout(hdr) != uklad:
        raise ValueError("FITS: układ danych z uchwytu inny niż z parsera")
    return raw, biezacy


def _fits_card_image(keyword: str, value: str, comment: str) -> tuple[bytes | None, str | None]:
    """Obraz 80 bajtów karty tekstowej `keyword = 'value' / comment` w układzie astropy (pole
    wartości stałego formatu, §4.2) albo `(None, powód)`. Round-trip: karta odczytana z obrazu
    ma dać tę samą nazwę, wartość i komentarz - astropy przy za długim komentarzu UCINA go po cichu
    (ostrzeżenie), a przy za długiej wartości składa CONTINUE; oba przypadki łapie ta kontrola."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        image = fits.Card(keyword, value, comment).image
        back = fits.Card.fromstring(image)
        zgodna = (len(image) == _FITS_RECORD and back.keyword == keyword
                  and back.value == value.rstrip() and (back.comment or "") == (comment or ""))
    if not zgodna:
        return None, (f"karta {keyword} z zastanym komentarzem nie mieści się w jednym rekordzie "
                      f"80 znaków")
    return image.encode("ascii"), None


def _fits_hdu_bounds(path: str, expected_hash: str | None):
    """Odczyt parserem (pod blokadą wołającego): `(hdr, start, data_start, hash)` albo
    `WriteResult('blocked')`/`Fallback`. Offsety są tu KANDYDATEM - rozstrzyga `_fits_region_checked`."""
    with fits.open(path, mode="readonly", memmap=False) as hdul:
        index, hdu = scan._select_hdu(hdul)
        hdr = hdu.header
        biezacy = scan._header_hash(hdr)
        if expected_hash is not None and biezacy != expected_hash:
            return WriteResult("blocked", "header_hash mismatch", None)
        if isinstance(hdu, fits.CompImageHDU):
            return Fallback("skompresowany master - nagłówek kafelkowy układa astropy")
        info = hdul.fileinfo(index)
        return hdr, info["hdrLoc"], info["datLoc"], biezacy


def _fits_inplace_plan(path: str, fh, ops: list[WriteOp], expected_hash: str | None):
    """Plan zapisu w miejscu dla FITS (pod blokadą) → `_InplacePlan` | `Fallback` | `WriteResult`.

    Kwalifikuje się wyłącznie `set` WARTOŚCI TEKSTOWEJ na karcie tekstowej występującej dokładnie
    raz, której nowy obraz (z ZASTANYM komentarzem - dług AR-7: tu komentarz nie ginie) mieści
    się w jednym rekordzie. Karta jest podmieniana w TYM SAMYM 80-bajtowym slocie, więc liczba
    kart, bloków 2880 B i długość nagłówka zostają. Kontrola hasha i reguły karty stoją PRZED
    kwalifikacją, więc odmawiają tak samo jak droga atomowa; `CHECKSUM`/`DATASUM` → odmowa."""
    granice = _fits_hdu_bounds(path, expected_hash)
    if not isinstance(granice, tuple):
        return granice
    hdr, start, data_start, biezacy = granice
    powod = _ops_violation(ops, lambda op: op.op == "add" or _count_keyword(hdr, op.keyword) == 0)
    if powod is not None:
        return WriteResult("blocked", powod, None)
    sumy = [k for k in _FITS_SUM_KEYWORDS if k in hdr]
    if sumy:
        return WriteResult("blocked", f"FITS z sumą kontrolną ({', '.join(sumy)}) - zapis nagłówka "
                                      f"unieważniłby ją, a pisarz jej nie przelicza", None)
    obrazy: dict[str, tuple[bytes, str]] = {}
    for op in ops:
        kw = op.keyword.strip().upper()
        if op.op != "set" or op.value_type != "str":
            return Fallback(f"operacja {op.op}/{op.value_type} na {kw} - układ karty zostaje "
                            f"przy astropy")
        if kw in _FITS_NOT_INPLACE or kw in _FITS_LAYOUT_KEYWORDS or kw in obrazy:
            return Fallback(f"karta {kw} nie jest zwykłą kartą tekstową")
        ile = _count_keyword(hdr, kw)
        if ile != 1 or op.idx not in (None, 0):
            return Fallback(f"karta {kw} występuje {ile} razy")
        card = hdr.cards[kw]
        if not isinstance(card.value, str):
            return Fallback(f"zastana wartość {kw} nie jest tekstem")
        image, powod = _fits_card_image(kw, str(op.value), card.comment)
        if image is None:
            return Fallback(powod)
        obrazy[kw] = (image, str(op.value))
    want = [dataclasses.replace(c, value_raw=obrazy[c.keyword][1].rstrip())
            if c.keyword in obrazy else c for c in scan._parse_cards(hdr)]
    uklad = _fits_layout(hdr)
    sprawdzony = _fits_region_checked(fh, start, data_start, biezacy, uklad)
    if isinstance(sprawdzony, WriteResult):
        return sprawdzony
    raw, _ = sprawdzony
    records = [raw[i:i + _FITS_RECORD] for i in range(0, len(raw), _FITS_RECORD)]
    for kw, (image, _) in obrazy.items():
        nazwa = kw.ljust(8).encode("ascii")
        trafienia = [i for i, r in enumerate(records) if r[:8] == nazwa and r[8:10] == b"= "]
        if len(trafienia) != 1:
            return Fallback(f"karta {kw} stoi w {len(trafienia)} rekordach wartości")
        i = trafienia[0]
        if i + 1 < len(records) and records[i + 1][:8] == b"CONTINUE":
            return Fallback(f"karta {kw} ma kontynuację CONTINUE")
        records[i] = image
    new_raw = b"".join(records)
    # Weryfikacja łaty PRZED zapisem (bliźniak `_xisf_verify`): karty z nowego nagłówka, wyłuskane
    # TĄ SAMĄ funkcją co skan, == karty sprzed łaty z podmienioną wartością; układ danych bez zmian.
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
    udał, i jedyną uczciwą drogą dalej jest odzysk."""
    try:
        journal.phase(faza, reason)
    except Exception as exc:  # noqa: BLE001
        return f"faza '{faza}' NIE zapisana w dzienniku ({type(exc).__name__}: {exc}) - lokacja " \
               f"zostaje izolowana"
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
            return WriteResult("blocked", "nagłówek na dysku zmienił się między odczytem "
                                          "a zapisem - plik nietknięty", None)
        kotwica = koperta_sha1 = None
        if anchor is not None:
            if (anchor.strict or anchor.file_sha1 is None
                    or scan._mtime_iso(st) != anchor.mtime):
                kotwica = _sha1_uchwytu(fh)
                if anchor.file_sha1 is not None and kotwica != anchor.file_sha1:
                    return WriteResult("blocked", "plik zmienił się od ostatniego skanu (sha1 "
                                                  "całego pliku inny niż w bazie) - kontrola danych "
                                                  "po zapisie nie miałaby kotwicy; najpierw skan, "
                                                  "plik nietknięty", None)
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
            return WriteResult("failed", f"backup/dziennik operacji NIE powstał, więc zapisu nie "
                                         f"było - plik nietknięty: {type(exc).__name__}: {exc}",
                               None)
        ruszony = True
        if zakres != (0, 0):
            fh.seek(plan.region_start + zakres[0])
            fh.write(plan.new_region[zakres[0]:zakres[1]])
        fh.flush()
        os.fsync(fh.fileno())
    except Exception as exc:  # noqa: BLE001 - raport zamiast wyjątku w warstwie zapisu
        if not ruszony:
            return WriteResult("failed", f"{type(exc).__name__}: {exc}", None)
        powod = f"zapis w miejscu przerwany - bajty nagłówka mogły się zmienić: " \
                f"{type(exc).__name__}: {exc}"
        dopisek = _faza(journal, "unverified", powod)
        return WriteResult("failed", f"{powod}; {dopisek}" if dopisek else powod,
                           plan.post_hash, backup_text, in_place=True)
    wynik = _verify_inplace(plan, size, probka, backup_text)
    dopisek = _faza(journal, "written" if wynik.status == "applied" else "unverified", wynik.reason)
    if dopisek and wynik.status == "applied":
        return WriteResult("failed", f"plik ZMIENIONY w miejscu i zweryfikowany, ale {dopisek} - "
                                     f"operacja NIEUKOŃCZONA", plan.post_hash, backup_text,
                           in_place=True)
    if dopisek:
        wynik = dataclasses.replace(wynik, reason=f"{wynik.reason}; {dopisek}")
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
        return WriteResult("failed", f"plik ZMIENIONY w miejscu, ale odczyt kontrolny klienta "
                                     f"padł - {type(exc).__name__}: {exc}",
                           plan.post_hash, backup_text, in_place=True)
    rozjazdy = [nazwa for nazwa, zgodne in (
        ("rozmiar pliku", size_po == size), ("bajty nagłówka", region_po == plan.new_region),
        ("próbka danych", probka_po == probka), ("header_hash", post == plan.post_hash))
        if not zgodne]
    if rozjazdy:
        return WriteResult("failed", f"plik ZMIENIONY w miejscu, ale odczyt kontrolny klienta "
                                     f"nie zgadza się: {', '.join(rozjazdy)}",
                           plan.post_hash, backup_text, in_place=True)
    return WriteResult("applied", None, post, backup_text, in_place=True)


def inplace_route(filetype, keyword: str, value: str, value_type, comment) -> str | None:
    """PRZEWIDYWANIE drogi zapisu `set` jednej karty tekstowej z faktów bazy, bez otwierania pliku
    (podgląd planu): `None` = w miejscu, tekst = powód drogi dotychczasowej. Reguła mieszczenia się
    karty FITS jest TA SAMA, której używa pisarz (`_fits_card_image`), więc podgląd i zapis nie mogą
    się rozjechać co do rekordu 80 znaków; resztę (liczba kart, CONTINUE, sumy kontrolne)
    rozstrzyga pisarz na pliku. XISF → `None`: brak rezerwy odmawia tak samo w obu drogach."""
    if filetype == "xisf":
        return None
    if value_type != "str":
        return f"zastana wartość {keyword} nie jest tekstem"
    return _fits_card_image(keyword, value, comment or "")[1]


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
            return WriteResult("failed", f"{type(exc).__name__}: {exc}", None)
        if isinstance(wynik, WriteResult):
            dopisek = f"zamknięcie uchwytu padło - {type(exc).__name__}: {exc}"
            return dataclasses.replace(
                wynik, reason=f"{wynik.reason}; {dopisek}" if wynik.reason else dopisek)
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
        return WriteResult("blocked", "format RAW jest read-only (#2)", None)
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
    hashu); region = stan sprzed commitu → 'blocked' „już cofnięte"; inny region → 'blocked'.
    `anchor` = kotwica bazy jak w `write_changes_inplace`."""
    if _is_raw(path):
        return WriteResult("blocked", "format RAW jest read-only (#2)", None)
    path = os.fspath(path)
    journal = journal or _NullJournal()

    def _dzialanie(fh):
        st = os.fstat(fh.fileno())
        if st.st_size != op_file_size or (op_file_ino and st.st_ino and st.st_ino != op_file_ino):
            return Fallback("plik podmieniony od commitu (rozmiar/st_ino) - cofnięcie atomowe")
        fh.seek(backup.offset)
        biezacy = fh.read(len(backup.region))
        if biezacy == backup.region:
            return WriteResult("blocked", "już cofnięte - region nagłówka jest stanem sprzed commitu",
                               None)
        if biezacy != op_new_region:
            return WriteResult("blocked", "plik zmienił się od commitu - region nagłówka nie jest "
                                          "tym, który commit zapisał", None)
        plan = _InplacePlan(backup.fmt, path, backup.offset, biezacy, backup.region, op_post_hash,
                            backup.pre_hash)
        return _apply_inplace(plan, fh, journal, anchor)
    return _pod_blokada(path, _dzialanie)


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
        return WriteResult("blocked", "format RAW jest read-only (#2)", None)
    path = os.fspath(path)
    return _pod_blokada(path, lambda fh: _odzysk_pod_blokada(fh, path, spec))


_RECZNA = ("nierozstrzygalne - przywróć plik z pełnej kopii ręcznie, potem zwolnij izolację "
           "(`repo.release_inplace_op`)")


def _odzysk_pod_blokada(fh, path: str, spec: OpSpec) -> WriteResult:
    """Rdzeń `recover_region` na uchwycie blokady `fh` - wspólny dla pisarza i orkiestracji
    `recover_torn`, która pod TĄ SAMĄ blokadą sprawdza fazę operacji przed i utrwala ją po."""
    st = os.fstat(fh.fileno())
    if st.st_size != spec.file_size or (spec.file_ino and st.st_ino
                                        and st.st_ino != spec.file_ino):
        return WriteResult("blocked", f"inny plik niż w chwili zapisu (rozmiar/st_ino); {_RECZNA}",
                           None)
    fh.seek(spec.region_offset)
    biezacy = fh.read(len(spec.old_region))
    if not _stan_posredni(biezacy, spec):
        try:
            _post_hash(path)
            czytelny = True
        except Exception:  # noqa: BLE001
            czytelny = False
        if czytelny:
            return WriteResult("blocked", "to nie jest rozdarcie tej operacji - nagłówek jest "
                                          "czytelny, ale to nie jest żaden stan pośredni "
                                          "zapisu (obca zmiana); odzysk odmawia", None)
        return WriteResult("blocked", f"to nie jest rozdarcie tej operacji; {_RECZNA}", None)
    plan = _InplacePlan(spec.fmt, path, spec.region_offset, biezacy, spec.old_region, "",
                        spec.pre_hash)
    return _apply_inplace(plan, fh, _NullJournal())


# ============================================================ odczyty stagingu (core — literały)


def pending_for_run(con, run_id):
    """Wpisy stagingu przebiegu (do commitu i do szuflady GUI). Kolejność `id` = kolejność stagingu."""
    return con.execute(
        "SELECT id, location_id, keyword, idx, op, old_value, new_value, new_type, new_comment, "
        "       expected_header_hash, status, reason "
        "FROM pending_changes WHERE run_id = ? ORDER BY id",
        (run_id,),
    ).fetchall()


def backups_for_commit(con, commit_id):
    """Backupy nagłówków commitu (do undo)."""
    return con.execute(
        "SELECT id, location_id, hdu_index, header_text, post_hash "
        "FROM header_backups WHERE commit_id = ? ORDER BY id",
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
    status: str  # 'applied' | 'blocked' | 'failed' | 'skipped' | 'restored'
    reason: str | None = None


@dataclasses.dataclass(frozen=True)
class CommitResult:
    run_id: str
    commit_id: int | None  # None gdy żaden plik nie został podmieniony (applied ani failed po podmianie)
    applied: list[FileResult]
    blocked: list[FileResult]
    failed: list[FileResult]
    skipped: list[FileResult]
    cancelled: bool = False
    # Podzbiór `applied` zapisany W MIEJSCU (`commit(inplace=True)`); reszta `applied` poszła drogą
    # dotychczasową, a jej `FileResult.reason` mówi, czemu (`Fallback.reason`).
    in_place: list[FileResult] = dataclasses.field(default_factory=list)


@dataclasses.dataclass(frozen=True)
class UndoResult:
    commit_id: int
    restored: list[FileResult]
    blocked: list[FileResult]
    failed: list[FileResult]
    cancelled: bool = False


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


def _resync(con, path, volume, *, now, actor="user:local", expect_sha1_data=None, kontrola=None):
    """RE-SYNC bazy po mutacji pliku - REUŻYWA znanej-ścieżki skanu (SPOT, R#2). `scan_file`
    (read-only, świeże hasze/nagłówek/karty) → `ingest_record`: `refresh_location` odświeża fakty
    kopii + zeznanie + `cards` + `frame.camera_id/kind` z eventami (actor="user:local"). Wymaga
    BRAKU otwartej transakcji (refresh bierze BEGIN IMMEDIATE) - funkcje stagingu `repo` commitują
    same, więc jest czysto.

    `expect_sha1_data` (zapis w miejscu): tożsamość danych, którą plik MA mieć po zapisie. Re-sync
    i tak czyta cały plik, więc to pełny dowód nietkniętych danych za darmo. Rozjazd → zwraca powód
    i NIE wciąga rekordu: `ingest_record` uznałby go za podmianę treści i rozdwoił klatkę
    (nowy frame + osierocony stary z zeznaniem i obiektem). Zwraca `None`, gdy wciągnął.

    `kontrola` (zapis w miejscu, `_KontrolaDanych`, astra 2026-09-27): `sha1_data` obejmuje tylko
    wybrane HDU / pierwszy obraz, więc przed wciągnięciem rekordu dwa kolejne warunki - nagłówek
    na dysku to ten, który operacja zapisała (`header_hash`), i plik z PODSTAWIONYM starym regionem
    operacji ma sha1 kotwicy sprzed zapisu (żaden bajt poza regionem się nie zmienił). Brak kotwicy
    to też odmowa: bez niej kontrola nie istnieje. Ingest BEZ generacji (`inplace_gen=None`) - to
    re-sync operacji, która sama izoluje lokację, więc nie może odrzucić sam siebie."""
    rec = scan.scan_file(path)
    niezgodne = _kontrola_danych(path, rec, expect_sha1_data, kontrola)
    if niezgodne is not None:
        return niezgodne
    scan.ingest_record(con, rec, volume=volume, now=now, summary=scan.ScanSummary(), actor=actor)
    return None


def _kontrola_danych(path, rec, expect_sha1_data, kontrola) -> str | None:
    """Warunki, które plik po mutacji musi spełnić, zanim re-sync go wciągnie (zob. `_resync`):
    `None` = zgodny, tekst = powód niezgodności. Wspólne dla re-syncu i drogi powrotu z `written`
    (`_powrot_z_written`), która pyta o werdykt bez wciągania.

    Kotwicą jest sha1 pliku SPRZED operacji, utrwalony przy operacji (`inplace_op.anchor_sha1`,
    0023). Równość sha1 pliku z kotwicą NIE jest skrótem (astra, 2026-09-27): dawniej kotwicą była
    mutowalna `location.file_sha1`, a „sha1 == kotwica" przepuszczał każdy plik, którego fakty ktoś
    zdążył wciągnąć - także plik z bajtem zmienionym poza nagłówkiem. Kotwica niezmienna od chwili
    utrwalenia pozwala liczyć kontrolę od nowa przy każdym ponowieniu - kosztem tego samego pełnego
    odczytu, który zwykła ścieżka i tak robi."""
    if expect_sha1_data is not None and rec.sha1_data != expect_sha1_data:
        return (f"plik ZMIENIONY, ale sha1_data po zapisie ({rec.sha1_data}) różni się od "
                f"tożsamości klatki - baza NIE zsynchronizowana")
    if kontrola is None:
        return None
    if rec.header_hash != kontrola.header_hash:
        return ("plik ZMIENIONY, ale nagłówek na dysku nie jest tym, który operacja zapisała "
                "(header_hash) - baza NIE zsynchronizowana")
    if kontrola.anchor_sha1 is None:
        return ("brak kotwicy sha1 pliku sprzed zapisu - kontrola bajtów poza nagłówkiem "
                "niemożliwa, baza NIE zsynchronizowana")
    if _sha1_z_podstawieniem(path, kontrola.offset, kontrola.old_region) != kontrola.anchor_sha1:
        return ("plik ZMIENIONY, a bajty POZA regionem nagłówka różnią się od pliku sprzed "
                "zapisu (sha1 pliku z podstawionym starym regionem != kotwica operacji) - "
                "baza NIE zsynchronizowana")
    return None


def _powod_izolacji(op) -> str:
    """Powód odmowy mutacji pliku lokacji z operacją izolującą - z drogą naprawy właściwą fazie."""
    droga = (f"najpierw odzysk: recover_torn({op['id']})"
             if op["phase"] in repo.INPLACE_OPEN_PHASES
             else f"najpierw dokończenie: finish_inplace({op['id']}), a gdy kontrola danych nie "
                  f"przechodzi - powrót: recover_torn({op['id']})")
    return (f"lokacja ma nieukończony zapis w miejscu (operacja {op['id']}, {op['kind']}, faza "
            f"{op['phase']}) - plik jest izolowany; {droga}")


def _powod_konfliktu(op) -> str:
    """Powód odmowy podmiany drogą atomową (`repo.InplaceConflict`, straż podmiany)."""
    if op["phase"] in repo.INPLACE_ISOLATING_PHASES:
        return _powod_izolacji(op)
    return (f"lokacja dostała zapis w miejscu (operacja {op['id']}, {op['kind']}, faza "
            f"{op['phase']}) po odczycie pliku do podmiany - plik tymczasowy powstał ze stanu "
            f"sprzed niego; podmiany nie było, plik nietknięty - ponów po odświeżeniu stagingu")


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
    'pending', których ponowienie nie znajdowało."""
    op = con.execute("SELECT * FROM inplace_op WHERE id = ?", (op_id,)).fetchone()
    if op is None:
        return WriteResult("failed", f"brak operacji {op_id}", None)
    loc = _location(con, int(op["location_id"]))
    if loc is None:
        return WriteResult("failed", "brak location w bazie", None)
    spec = _spec_z_operacji(op)
    kontrola = _KontrolaDanych(spec.region_offset, spec.old_region,
                               _kotwica_operacji(con, op, loc), spec.post_hash)

    def _dzialanie(fh):
        faza = repo.inplace_op_phase(con, op_id)
        if faza != "written":
            return WriteResult("blocked", f"operacja {op_id} jest w fazie {faza}, nie czeka na "
                                          f"dokończenie", None)
        if repo.newer_inplace_op(con, location_id=loc["id"], op_id=op_id):
            return WriteResult("blocked", f"lokacja ma operację nowszą niż {op_id} - dokończenie "
                                          f"odmawia", None)
        st = os.fstat(fh.fileno())
        if st.st_size != spec.file_size or (spec.file_ino and st.st_ino
                                            and st.st_ino != spec.file_ino):
            return WriteResult("blocked", f"inny plik niż w chwili zapisu (rozmiar/st_ino); "
                                          f"{_RECZNA}", None)
        fh.seek(spec.region_offset)
        biezacy = fh.read(len(spec.new_region))
        if biezacy != spec.new_region:
            droga = (f"przerwany powrót tej operacji - ponów: recover_torn({op_id})"
                     if _stan_posredni(biezacy, spec) else _RECZNA)
            return WriteResult("blocked", f"region nagłówka na dysku nie jest wynikiem operacji "
                                          f"{op_id} - plik zmienił się od zapisu; {droga}", None)
        try:
            niezgodne = _resync(con, loc["path"], loc["volume"], now=now,
                                expect_sha1_data=loc["sha1_data"], kontrola=kontrola)
        except Exception as exc:  # noqa: BLE001 - wsad idzie dalej, operacja zostaje `written`
            return WriteResult("failed", f"plik ZMIENIONY, ale re-sync padł - "
                                         f"{type(exc).__name__}: {exc}; ponów: "
                                         f"finish_inplace({op_id})", None)
        if niezgodne is not None:
            return WriteResult("failed", f"{niezgodne}; kontrola danych NIE przeszła - droga "
                                         f"powrotu: recover_torn({op_id}) przywraca stary nagłówek "
                                         f"w miejscu i zwalnia plik do pełnego skanu", None)
        try:
            repo.finish_inplace_op(con, op_id=op_id, now=now)
        except Exception as exc:  # noqa: BLE001
            return WriteResult("failed", f"baza zsynchronizowana, ale faza 'synced' NIE zapisana "
                                         f"({type(exc).__name__}: {exc}); ponów: "
                                         f"finish_inplace({op_id})", None)
        return WriteResult("applied", None, spec.post_hash)
    return _pod_blokada(loc["path"], _dzialanie)


def finish_inplace(con, op_id, *, now) -> FileResult:
    """PONOWIENIE DOKOŃCZENIA operacji zapisu w miejscu w fazie `written` (zapis zweryfikowany, ale
    kontrola danych, re-sync albo utrwalenie fazy padły, albo proces przerwał się przed re-synciem -
    lokacja izolowana). `_dokoncz` pod blokadą: kontrola danych od nowa wobec kotwicy operacji,
    re-sync i JEDNA transakcja zamknięcia (faza `synced`, wpisy stagingu ZWIĄZANE z operacją →
    'applied', zgaszenie nagrobka ręki, gdy łata wpisała `OBJECT` - `repo.finish_inplace_op`).
    Zwraca `FileResult` ('applied' | 'blocked' | 'failed')."""
    op = con.execute("SELECT * FROM inplace_op WHERE id = ?", (op_id,)).fetchone()
    if op is None:
        return FileResult(0, "", "failed", f"brak operacji {op_id}")
    loc = _location(con, int(op["location_id"]))
    if loc is None:
        return FileResult(int(op["location_id"]), "", "failed", "brak location w bazie")
    res = _dokoncz(con, op_id, now=now)
    return FileResult(loc["id"], loc["path"], res.status, res.reason)


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
    kolejność (backup PO podmianie, D-X-14) zostawiała plik zmieniony bez drogi powrotu.

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
    dodatkowego pełnego odczytu - z drogą powrotu dla tego samego przypadku."""
    clock = clock or (lambda: now)
    pending = [r for r in pending_for_run(con, run_id) if r["status"] == "pending"]
    groups = _group_by_location(pending)
    total = len(groups)

    applied: list[FileResult] = []
    blocked: list[FileResult] = []
    failed: list[FileResult] = []
    skipped: list[FileResult] = []
    in_place: list[FileResult] = []
    commit_id: int | None = None
    cancelled = False
    done = 0

    def _report(path, status):
        nonlocal done
        done += 1
        if progress is not None:
            progress(done, total, path, status)

    def _mark(rows, status, reason):
        for r in rows:
            repo.set_pending_status(con, pending_id=r["id"], status=status, reason=reason)

    for location_id, rows in groups:
        if should_cancel is not None and should_cancel():
            cancelled = True
            break
        loc = _location(con, location_id)
        if loc is None:
            _mark(rows, "failed", "brak location w bazie")
            failed.append(FileResult(location_id, "", "failed", "brak location w bazie"))
            _report("", "failed")
            continue
        path = loc["path"]
        if not loc["present"]:
            reason = "kopia zniknęła (present=0)"
            _mark(rows, "skipped", reason)
            skipped.append(FileResult(location_id, path, "skipped", reason))
            _report(path, "skipped")
            continue
        if loc["compressed"]:
            reason = "skompresowany master — edycja poza krokiem 4"
            _mark(rows, "skipped", reason)
            skipped.append(FileResult(location_id, path, "skipped", reason))
            _report(path, "skipped")
            continue
        # Generacja dziennika PRZED bramką: straż podmiany drogi atomowej odbije operację zaczętą
        # po tej chwili (plik tymczasowy powstanie ze stanu sprzed niej).
        gen = repo.inplace_generation(con)
        izolujaca = repo.isolating_inplace_op(con, location_id)
        if izolujaca is not None:           # obie drogi: plik po nieukończonym zapisie w miejscu
            reason = _powod_izolacji(izolujaca)
            _mark(rows, "blocked", reason)
            blocked.append(FileResult(location_id, path, "blocked", reason))
            _report(path, "blocked")
            continue

        ops = [WriteOp(keyword=r["keyword"], op=r["op"], value=r["new_value"],
                       value_type=r["new_type"], idx=r["idx"], comment=r["new_comment"])
               for r in rows]
        expected = rows[0]["expected_header_hash"]  # kotwica stagingu (R#7)

        def _persist(backup_text, post_hash, _lid=location_id, _hdu=loc["hdu_index"]):
            # Backup PRZED podmianą (droga atomowa): commit powstaje przy pierwszym pliku, który
            # naprawdę ma być ruszony.
            nonlocal commit_id
            if commit_id is None:
                commit_id = repo.insert_commit(con, run_id=run_id, now=clock(),
                                               summary=f"run {run_id}")
            repo.insert_header_backup(con, commit_id=commit_id, location_id=_lid,
                                      hdu_index=_hdu, header_text=backup_text,
                                      post_hash=post_hash)

        class _Dziennik:
            """Dziennik commitu w miejscu: backup + commit + operacja + wiązanie wpisów stagingu
            jedną transakcją."""
            op_id = None

            def begin(self, spec, backup_text, _lid=location_id, _hdu=loc["hdu_index"],
                      _ids=tuple(r["id"] for r in rows)):
                nonlocal commit_id
                commit_id, self.op_id = repo.begin_inplace_commit(
                    con, run_id=run_id, commit_id=commit_id, location_id=_lid, hdu_index=_hdu,
                    header_text=backup_text, spec=spec, now=clock(), pending_ids=_ids)

            def phase(self, faza, reason=None):
                repo.set_inplace_op_phase(con, op_id=self.op_id, phase=faza, now=now,
                                          reason=reason, expect_phase="writing")

        def _straz(_lid=location_id, _gen=gen):
            return repo.guard_file_replace(con, location_id=_lid, generation=_gen)

        droga = None                                 # powód drogi atomowej w trybie `inplace`
        res = None
        dziennik = _Dziennik()
        if inplace:
            res = write_changes_inplace(
                path, ops, expected, journal=dziennik,
                anchor=FileAnchor(loc["file_sha1"], loc["mtime"], strict=not fallback))
            if isinstance(res, Fallback):
                if not fallback:
                    res = WriteResult("blocked", f"nie mieści się w miejscu (tryb bez spadku): "
                                                 f"{res.reason}", None)
                else:
                    droga = f"droga dotychczasowa: {res.reason}"
                    res = None
        if res is None:
            res = write_changes(path, ops, expected, persist_backup=_persist,
                                replace_guard=_straz)                       # os.replace pod strażą

        if res.backup_text is None:       # zapisu nie było: odmowa albo awaria przed plikiem
            status = "blocked" if res.status == "blocked" else "failed"
            _mark(rows, status, res.reason)
            (blocked if status == "blocked" else failed).append(
                FileResult(location_id, path, status, res.reason))
            _report(path, status)
            continue
        if res.status != "applied":
            # Backup JEST (powstał przed zapisem), więc undo cofnie plik, o ile leży na nim to, co
            # zapisaliśmy (`post_hash`); plik rozdarty w miejscu naprawia `recover_torn`. Re-syncu
            # NIE robimy - baza opisuje bajty POTWIERDZONE. Nagrobek ręki też zostaje.
            naprawa = (f"; lokacja IZOLOWANA od skanu, odzysk: recover_torn({dziennik.op_id})"
                       if res.in_place else "")
            reason = (f"{res.reason}; backup do cofnięcia zapisany w commicie {commit_id}"
                      f"{naprawa}")
            _mark(rows, "failed", reason)
            failed.append(FileResult(location_id, path, "failed", reason))
            _report(path, "failed")
            continue
        if res.in_place:
            # PLIK→DB pod blokadą: region == wynik, kontrola danych (bajty poza nagłówkiem), re-sync
            # i JEDNA transakcja zamknięcia (`synced` + wpisy 'applied' + nagrobek). Porażka zostawia
            # lokację IZOLOWANĄ w fazie `written` (skan jej nie ruszy, a nie „naprawi ponownym
            # re-skanem") - drogę dalej (`finish_inplace` / `recover_torn`) niesie powód.
            koniec = _dokoncz(con, dziennik.op_id, now=now)
            if koniec.status != "applied":
                droga_dalej = ("" if koniec.status == "failed" or "recover_torn" in koniec.reason
                               else f", zwolnienie ręką: repo.release_inplace_op({dziennik.op_id})")
                reason = (f"{koniec.reason}; backup do cofnięcia zapisany w commicie {commit_id}; "
                          f"lokacja IZOLOWANA od skanu{droga_dalej}")
                _mark(rows, "failed", reason)
                failed.append(FileResult(location_id, path, "failed", reason))
                _report(path, "failed")
                continue
            # Wpisy stagingu i nagrobek zamknęło dokończenie, atomowo z fazą.
            wynik = FileResult(location_id, path, "applied", droga)
            applied.append(wynik)
            in_place.append(wynik)
            _report(path, "applied")
            continue
        try:                              # droga atomowa: PLIK→DB (T8); pełny odczyt pliku
            niezgodne = _resync(con, path, loc["volume"], now=now,
                                expect_sha1_data=loc["sha1_data"])
        except Exception as exc:  # noqa: BLE001 - plik zapisany, pętla idzie dalej
            # Wsad to tysiące pełnych odczytów po SMB - jedna czkawka udziału nie może zatrzymać
            # przebiegu z plikiem zapisanym, a bez statusu. Bazę drogi atomowej naprawi ponowny
            # re-skan (T8) - ta droga lokacji nie izoluje.
            niezgodne = f"plik ZMIENIONY, ale re-sync padł - {type(exc).__name__}: {exc}"
        if niezgodne is not None:
            reason = f"{niezgodne}; backup do cofnięcia zapisany w commicie {commit_id}"
            _mark(rows, "failed", reason)
            failed.append(FileResult(location_id, path, "failed", reason))
            _report(path, "failed")
            continue
        # NAGROBEK RĘKI GAŚNIE TU, a nie w ścieżce skanu (S2b, §4/14b-c). Klatka cofnięta ma
        # `object_source='user_cleared'` i drabina ją POMIJA - bez tego gestu zostałaby poza osią na
        # zawsze, nawet po dopisaniu karty. Wyzwalaczem jest WPISANIE `OBJECT` do TEGO pliku, nie
        # samo odświeżenie zeznania: każdy skan odświeża zeznanie i gasiłby werdykt, którego nikt
        # nie odwołał. Droga w miejscu gasi go tą samą klingą w transakcji dokończenia
        # (`repo.finish_inplace_op`).
        if any(op.keyword == "OBJECT" for op in ops):
            repo.clear_object_tombstone(con, frame_id=loc["frame_id"], now=now)
        _mark(rows, "applied", None)
        applied.append(FileResult(location_id, path, "applied", droga))
        _report(path, "applied")

    return CommitResult(run_id, commit_id, applied, blocked, failed, skipped, cancelled,
                        in_place)


# ============================================================ RENAME "Nazwy z faktów" (trzecia operacja)
# Rename PLIKU = mutacja → mieszka w tej klindze (jak os.replace writebacku). Prymityw `os.rename`
# (NIE `os.replace`): na Windows (tor R:/NAS) rzuca `FileExistsError` gdy cel istnieje = twardy backstop.
# Anty-clobber DWUWARSTWOWY (R3 #1/#3): (1) `os.path.exists(new)` — brama PRZENOŚNA (na POSIX `os.rename`
# CICHO nadpisuje, więc rename-fail sam nie wystarcza — R3-P2 #3); (2) `repo.relocate_location` re-sprawdza
# `UNIQUE(volume,new_path)` atomowo. Kolejność commitu: DB/dysk-check → `os.rename` → `relocate_location`
# (UPDATE path + event, T8: plik-first; crash pomiędzy → re-skan naprawia). Wiersz 'applied' sam jest
# rekordem undo. `os.rename` żyje TU (meta-test: `rename` ∈ OS_MUTATORS, DOOR=writeback.py).


@dataclasses.dataclass(frozen=True)
class RenameFileResult:
    status: str            # 'applied' | 'blocked' | 'failed'
    reason: str | None


def rename_file(old_path, new_path) -> RenameFileResult:
    """Prymityw renamu pliku (KLINGA). Brama anty-clobber: źródło istnieje ORAZ cel NIE istnieje na
    dysku (przenośne) → `os.rename` (Windows: `FileExistsError` przy wyścigu = backstop). Rename w tym
    samym katalogu = atomowy na wolumenie. Zwraca status; wołający (`commit_renames`) mapuje na staging."""
    old_path = os.fspath(old_path)
    new_path = os.fspath(new_path)
    try:
        if not os.path.exists(old_path):
            return RenameFileResult("blocked", "źródło nie istnieje na dysku")
        if os.path.exists(new_path):
            return RenameFileResult("blocked", "cel już istnieje na dysku (anty-clobber)")
        os.rename(old_path, new_path)
    except Exception as exc:  # noqa: BLE001 — raport zamiast wyjątku w warstwie zapisu
        return RenameFileResult("failed", f"{type(exc).__name__}: {exc}")
    return RenameFileResult("applied", None)


def renames_for_run(con, run_id):
    """Wpisy stagingu renamu przebiegu (commit + szuflada GUI). Kolejność `id` = kolejność stagingu."""
    return con.execute(
        "SELECT id, location_id, old_path, new_path, expected_mtime, status, reason "
        "FROM pending_renames WHERE run_id = ? ORDER BY id",
        (run_id,),
    ).fetchall()


def _location_rename(con, location_id):
    """Wiersz location do renamu: id, volume, path, mtime, present (kotwica anty-stale)."""
    return con.execute(
        "SELECT id, volume, path, mtime, present FROM location WHERE id = ?",
        (location_id,),
    ).fetchone()


def commit_renames(con, run_id, *, now,
                   progress: Callable[[int, int, str, str], None] | None = None,
                   should_cancel: Callable[[], bool] | None = None) -> CommitResult:
    """Zapisz `pending_renames` (status 'pending') przebiegu na dysk. Per wiersz: kotwica (present +
    `mtime`==staged + `path`==`old_path` + brak wiersza `location(volume,new_path)` — R3 #3) →
    `rename_file` (`os.rename`, anty-clobber dyskowy R3 #1) → `repo.relocate_location` (UPDATE + event,
    NIE ingest — R2 #1). Kotwica-mtime niezmienna po renamie (rename nie tyka treści), więc re-commit
    po udanym renamie widzi już `path==new_path` → relocate idempotentny. Utrwalanie per plik (funkcje
    `repo` commitują), więc anulowanie zostawia zrobione 'applied', resztę 'pending'. `progress(done,
    total, path, status)` po KAŻDYM pliku (Qt-wolne). Zwraca `CommitResult` (`commit_id` zawsze None —
    rename bez tabeli commitów; wiersz 'applied' sam jest undo-rekordem)."""
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
        loc = _location_rename(con, location_id)
        if loc is None:
            repo.set_rename_status(con, rename_id=rid, status="failed", reason="brak location")
            failed.append(FileResult(location_id, old_path, "failed", "brak location"))
            _report(old_path, "failed")
            continue
        if not loc["present"]:
            reason = "kopia zniknęła (present=0)"
            repo.set_rename_status(con, rename_id=rid, status="skipped", reason=reason)
            skipped.append(FileResult(location_id, old_path, "skipped", reason))
            _report(old_path, "skipped")
            continue
        izolujaca = repo.isolating_inplace_op(con, location_id)
        if izolujaca is not None:          # plik po nieukończonym zapisie w miejscu - nie ruszamy
            reason = _powod_izolacji(izolujaca)
            repo.set_rename_status(con, rename_id=rid, status="blocked", reason=reason)
            blocked.append(FileResult(location_id, old_path, "blocked", reason))
            _report(old_path, "blocked")
            continue
        # Kotwica anty-stale: plik nietknięty od podglądu (mtime + ścieżka).
        if loc["mtime"] != r["expected_mtime"] or loc["path"] != old_path:
            reason = "plik zmieniony od podglądu (mtime/ścieżka)"
            repo.set_rename_status(con, rename_id=rid, status="blocked", reason=reason)
            blocked.append(FileResult(location_id, old_path, "blocked", reason))
            _report(old_path, "blocked")
            continue
        # Anty-clobber W BAZIE PRZED renamem (R3 #3): brak INNEGO wiersza z celem (torn-state guard).
        db_clash = con.execute(
            "SELECT id FROM location WHERE volume = ? AND path = ? AND id <> ?",
            (loc["volume"], new_path, location_id)).fetchone()
        if db_clash is not None:
            reason = f"cel zajęty w bazie (location:{db_clash['id']})"
            repo.set_rename_status(con, rename_id=rid, status="blocked", reason=reason)
            blocked.append(FileResult(location_id, old_path, "blocked", reason))
            _report(old_path, "blocked")
            continue

        res = rename_file(old_path, new_path)          # tu następuje os.rename
        if res.status == "applied":
            try:
                repo.relocate_location(con, location_id=location_id, new_path=new_path, now=now)
            except ValueError as exc:                  # wyścig DB po renamie (rzadki torn-state)
                repo.set_rename_status(con, rename_id=rid, status="failed", reason=str(exc))
                failed.append(FileResult(location_id, new_path, "failed", str(exc)))
                _report(new_path, "failed")
                continue
            repo.set_rename_status(con, rename_id=rid, status="applied", reason=None)
            applied.append(FileResult(location_id, new_path, "applied"))
            _report(new_path, "applied")
        elif res.status == "blocked":
            repo.set_rename_status(con, rename_id=rid, status="blocked", reason=res.reason)
            blocked.append(FileResult(location_id, old_path, "blocked", res.reason))
            _report(old_path, "blocked")
        else:
            repo.set_rename_status(con, rename_id=rid, status="failed", reason=res.reason)
            failed.append(FileResult(location_id, old_path, "failed", res.reason))
            _report(old_path, "failed")

    return CommitResult(run_id, None, applied, blocked, failed, skipped, cancelled)


def undo_renames(con, run_id, *, now,
                 progress: Callable[[int, int, str, str], None] | None = None,
                 should_cancel: Callable[[], bool] | None = None) -> UndoResult:
    """Cofnij rename przebiegu: dla wierszy 'applied' odwrotny `os.rename` (new→old) pod TĄ SAMĄ bramą
    anty-clobber + `relocate_location` z powrotem na `old_path`. Kolejność odwrotna (jak stos). Gdy plik
    nie stoi na `new_path` (zmieniony od commitu) → 'blocked'. Udany rewert → status 'skipped' (powód
    „cofnięto") — dwukrotne undo pomija (tylko 'applied' cofane). `commit_id` w wyniku = run przebiegu
    (rename bez tabeli commitów). Bramka bezpieczna per plik."""
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
        loc = _location_rename(con, location_id)
        if loc is None or loc["path"] != new_path:
            reason = "plik nie stoi na nazwie z commitu"
            blocked.append(FileResult(location_id, new_path, "blocked", reason))
            _report(new_path, "blocked")
            continue
        izolujaca = repo.isolating_inplace_op(con, location_id)
        if izolujaca is not None:
            blocked.append(FileResult(location_id, new_path, "blocked",
                                      _powod_izolacji(izolujaca)))
            _report(new_path, "blocked")
            continue
        res = rename_file(new_path, old_path)          # odwrotny os.rename
        if res.status == "applied":
            try:
                repo.relocate_location(con, location_id=location_id, new_path=old_path, now=now)
            except ValueError as exc:
                repo.set_rename_status(con, rename_id=rid, status="failed", reason=str(exc))
                failed.append(FileResult(location_id, old_path, "failed", str(exc)))
                _report(old_path, "failed")
                continue
            repo.set_rename_status(con, rename_id=rid, status="skipped", reason="cofnięto (undo)")
            restored.append(FileResult(location_id, old_path, "restored"))
            _report(old_path, "restored")
        elif res.status == "blocked":
            blocked.append(FileResult(location_id, new_path, "blocked", res.reason))
            _report(new_path, "blocked")
        else:
            failed.append(FileResult(location_id, new_path, "failed", res.reason))
            _report(new_path, "failed")

    return UndoResult(run_id, restored, blocked, failed, cancelled)


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

    STAN „JUŻ COFNIĘTE" / „ZOSTAŁA SYNCHRONIZACJA":
      * droga w miejscu - z FAZY operacji `undo`: `written` → dokończenie (`_dokoncz`: pod blokadą
        region == wynik cofnięcia i brak nowszej operacji, dopiero wtedy re-sync z kontrolą danych
        → `synced`; inny region → 'blocked', astra 2026-09-27 - dawniej sam re-sync wciągał każdą
        późniejszą zmianę jako cofnięcie), `synced` → 'blocked' „już cofnięte"; operacja otwarta
        (commitu albo cofnięcia) → 'failed' z numerem operacji do odzysku (lokacja izolowana);
        commit w fazie `written` (jego re-sync padł) → najpierw jego dokończenie, potem cofnięcie;
      * droga atomowa - z pliku i kompletu faktów bazy: nagłówek na dysku = backup (dla koperty:
        CAŁY region bajt w bajt, dla backupu tekstowego: hash) i baza opisuje ten plik (`header_hash`
        ORAZ `mtime`) → 'blocked' „już cofnięte"; plik = backup, a baza nie → sam re-sync.

    BRAMKA IZOLACJI: operacja izolująca lokację spoza tego commitu (`repo.isolating_inplace_op`) →
    'blocked' z drogą naprawy, zero zapisu - w obu drogach. Droga atomowa powtarza ją pod strażą
    podmiany (`repo.guard_file_replace`, jak w `commit`): zapis w miejscu zaczęty po bramce odbija
    `os.replace` zamiast zostać przez nie starty."""
    backups = backups_for_commit(con, commit_id)
    total = len(backups)
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

    def _sync(loc, path, expect, powod):
        """Re-sync drogi atomowej (bez operacji w dzienniku)."""
        try:
            niezgodne = _resync(con, path, loc["volume"], now=now, expect_sha1_data=expect)
        except Exception as exc:  # noqa: BLE001 - nagłówek przywrócony, pętla idzie dalej
            niezgodne = (f"nagłówek PRZYWRÓCONY, ale re-sync padł - {type(exc).__name__}: {exc}; "
                         f"ponowne undo dokończy samą synchronizację")
        if niezgodne is not None:
            failed.append(FileResult(loc["id"], path, "failed", niezgodne))
            _report(path, "failed")
            return
        restored.append(FileResult(loc["id"], path, "restored", powod))
        _report(path, "restored")

    def _dokoncz_undo(loc, path, op_id, powod):
        """Dokończenie operacji cofnięcia w miejscu (`_dokoncz`) z wynikiem undo."""
        wynik = _dokoncz(con, op_id, now=now)
        if wynik.status == "applied":
            restored.append(FileResult(loc["id"], path, "restored", powod))
            _report(path, "restored")
        elif wynik.status == "blocked":
            _blok(loc, path, f"{wynik.reason}; lokacja IZOLOWANA od skanu")
        else:
            _pad(loc, path, f"nagłówek PRZYWRÓCONY, ale {wynik.reason}; lokacja IZOLOWANA od "
                            f"skanu - ponowne undo dokończy samą synchronizację")

    def _blok(loc, path, powod):
        blocked.append(FileResult(loc["id"], path, "blocked", powod))
        _report(path, "blocked")

    def _pad(loc, path, powod):
        failed.append(FileResult(loc["id"], path, "failed", powod))
        _report(path, "failed")

    for b in backups:
        if should_cancel is not None and should_cancel():
            cancelled = True
            break
        loc = _location(con, int(b["location_id"]))
        if loc is None:
            failed.append(FileResult(int(b["location_id"]), "", "failed", "brak location w bazie"))
            _report("", "failed")
            continue
        path = loc["path"]
        op_c = _ostatnia_operacja(con, commit_id, loc["id"], "commit")
        op_u = _ostatnia_operacja(con, commit_id, loc["id"], "undo")
        otwarta = next((o for o in (op_u, op_c)
                        if o is not None and o["phase"] in repo.INPLACE_OPEN_PHASES), None)
        if otwarta is not None:
            _pad(loc, path, f"przerwany zapis w miejscu (operacja {otwarta['id']}, "
                            f"{otwarta['kind']}) - lokacja izolowana; najpierw "
                            f"recover_torn({otwarta['id']})")
            continue
        if op_u is not None and op_u["phase"] == "written":
            _dokoncz_undo(loc, path, op_u["id"], "nagłówek był już przywrócony - dokończono "
                                                 "synchronizację bazy")
            continue
        if op_u is not None and op_u["phase"] == "synced":
            _blok(loc, path, "już cofnięte (operacja cofnięcia zamknięta)")
            continue
        if op_c is not None and op_c["phase"] == "written":
            # Commit zapisał i zweryfikował plik, ale jego re-sync padł (lokacja izolowana). Cofamy
            # dopiero stan, który baza zna: najpierw dokończenie commitu, potem zwykłe cofnięcie.
            koniec = _dokoncz(con, op_c["id"], now=now)
            if koniec.status != "applied":
                (_pad if koniec.status == "failed" else _blok)(
                    loc, path, f"commit nie jest dokończony (operacja {op_c['id']}): "
                               f"{koniec.reason}; lokacja IZOLOWANA od skanu")
                continue
            op_c = _ostatnia_operacja(con, commit_id, loc["id"], "commit")
            loc = _location(con, loc["id"])         # kotwica i mtime po dokończeniu commitu
        gen = repo.inplace_generation(con)          # przed bramką - dla straży podmiany atomowej
        izolujaca = repo.isolating_inplace_op(con, loc["id"])
        if izolujaca is not None:                   # nieukończony zapis spoza tego commitu
            _blok(loc, path, _powod_izolacji(izolujaca))
            continue
        try:
            env = RegionBackup.decode(b["header_text"])
        except ValueError as exc:
            _pad(loc, path, f"uszkodzona koperta backupu: {exc}")
            continue

        if env is not None and op_c is not None and op_c["phase"] == "synced":
            class _Dziennik:
                op_id = None

                def begin(self, spec, backup_text, _lid=loc["id"]):
                    self.op_id = repo.begin_inplace_undo(con, commit_id=commit_id,
                                                         location_id=_lid, spec=spec, now=now)

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
                    _dokoncz_undo(loc, path, dziennik.op_id, None)
                elif res.status == "blocked":
                    _blok(loc, path, res.reason)
                else:
                    dopisek = (f"; lokacja IZOLOWANA od skanu, odzysk: recover_torn({dziennik.op_id})"
                               if res.in_place else "")
                    _pad(loc, path, f"{res.reason}{dopisek}")
                continue

        # Droga atomowa: najpierw rozpoznanie „już przywrócone" z pliku i kompletu faktów bazy.
        try:
            if env is not None:
                with open(path, "rb") as fh:
                    fh.seek(env.offset)
                    na_miejscu = fh.read(len(env.region)) == env.region
            else:
                na_miejscu = _post_hash(path) == _backup_pre_hash(path, b["header_text"])
        except Exception:  # noqa: BLE001 - rozpoznanie tylko pomaga; decyduje pisarz niżej
            na_miejscu = False
        if na_miejscu:
            przywrocony = env.pre_hash if env is not None else _post_hash(path)
            try:
                mtime = scan._mtime_iso(os.stat(path))
            except OSError:
                mtime = None
            if loc["header_hash"] == przywrocony and loc["mtime"] == mtime:
                _blok(loc, path, "już cofnięte - nagłówek i baza opisują stan sprzed commitu")
            else:
                _sync(loc, path, loc["sha1_data"],
                      "nagłówek był już przywrócony - dokończono synchronizację bazy")
            continue
        res = write_full_header(
            path, b["header_text"], b["post_hash"],
            replace_guard=lambda _lid=loc["id"], _gen=gen: repo.guard_file_replace(
                con, location_id=_lid, generation=_gen))
        if res.status == "applied":
            _sync(loc, path, None, None)
        elif res.status == "blocked":
            _blok(loc, path, res.reason)
        else:
            _pad(loc, path, res.reason)

    return UndoResult(commit_id, restored, blocked, failed, cancelled)


def recover_torn(con, op_id, *, now) -> FileResult:
    """ODZYSK ROZDARTEGO NAGŁÓWKA po operacji `inplace_op.id` (astra Z11): tylko operacja OTWARTA
    (`writing`/`unverified`), tylko gdy region pliku pod blokadą jest jej stanem pośrednim
    (`_odzysk_pod_blokada`). Zwraca `FileResult` ('restored' | 'blocked' | 'failed').

    CAŁOŚĆ POD JEDNĄ BLOKADĄ PLIKU (astra, 2026-09-27): faza operacji czytana OD NOWA pod blokadą
    i brak późniejszej operacji tej lokacji - spóźnione drugie wywołanie, które widziało operację
    otwartą przed blokadą, nie cofnie nowszego, poprawnego zapisu (poprawny ponowny commit tej samej
    wartości zostawia region, który jest „stanem pośrednim" starej operacji). Po przywróceniu
    regionu re-sync z kontrolą danych (`sha1_data`, nagłówek sprzed operacji, sha1 całego pliku ==
    kotwica sprzed zapisu) i dopiero wtedy CAS fazy → `recovered`. Porażka re-syncu albo fazy
    zostawia operację OTWARTĄ (izolacja trwa), a ponowienie jest bezpieczne: region stary jest też
    stanem pośrednim, więc drugi odzysk nic nie pisze i powtarza samą kontrolę z re-synciem.

    OPERACJA `written` → DROGA POWROTU (`_powrot_z_written`, astra 2026-09-27): wyłącznie wtedy,
    gdy kontrola danych tej operacji NIE przechodzi. Inaczej lokacja stałaby zablokowana bez drogi
    wyjścia: dokończenie powtarza tę samą niezgodność, undo wymaga dokończenia, a skan izolowaną
    pomija."""
    op = con.execute("SELECT * FROM inplace_op WHERE id = ?", (op_id,)).fetchone()
    if op is None:
        return FileResult(0, "", "failed", f"brak operacji {op_id}")
    loc = _location(con, int(op["location_id"]))
    if loc is None:
        return FileResult(int(op["location_id"]), "", "failed", "brak location w bazie")
    path = loc["path"]
    if op["phase"] == "written":
        return _powrot_z_written(con, op, loc, now=now)
    if op["phase"] not in repo.INPLACE_OPEN_PHASES:
        return FileResult(loc["id"], path, "blocked",
                          f"operacja {op_id} nie jest otwarta ({op['phase']}) - odzysk dotyczy "
                          f"wyłącznie przerwanego zapisu")
    spec = _spec_z_operacji(op)
    kontrola = _KontrolaDanych(spec.region_offset, spec.old_region,
                               _kotwica_operacji(con, op, loc), spec.pre_hash)

    def _dzialanie(fh):
        faza = repo.inplace_op_phase(con, op_id)
        if faza not in repo.INPLACE_OPEN_PHASES:
            return WriteResult("blocked", f"operacja {op_id} przestała być otwarta ({faza}) - "
                                          f"odzysk odmawia", None)
        if repo.newer_inplace_op(con, location_id=loc["id"], op_id=op_id):
            return WriteResult("blocked", f"lokacja ma operację nowszą niż {op_id} - odzysk "
                                          f"odmawia, żeby nie cofnąć późniejszego zapisu", None)
        res = _odzysk_pod_blokada(fh, path, spec)
        if res.status != "applied":
            return res
        ponow = f"operacja zostaje otwarta, ponów recover_torn({op_id})"
        try:
            niezgodne = _resync(con, path, loc["volume"], now=now,
                                expect_sha1_data=loc["sha1_data"], kontrola=kontrola)
        except Exception as exc:  # noqa: BLE001
            niezgodne = f"region przywrócony, ale re-sync padł - {type(exc).__name__}: {exc}"
        if niezgodne is not None:
            return WriteResult("failed", f"{niezgodne}; {ponow}", None)
        try:
            repo.set_inplace_op_phase(con, op_id=op_id, phase="recovered", now=now,
                                      reason="region stary przywrócony (recover_torn)",
                                      expect_phase=faza)
        except Exception as exc:  # noqa: BLE001
            return WriteResult("failed", f"region przywrócony i baza zsynchronizowana, ale faza "
                                         f"'recovered' NIE zapisana ({type(exc).__name__}: {exc});"
                                         f" {ponow}", None)
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
    ponow = f"operacja zostaje 'written', ponów recover_torn({op_id})"

    def _dzialanie(fh):
        faza = repo.inplace_op_phase(con, op_id)
        if faza != "written":
            return WriteResult("blocked", f"operacja {op_id} jest w fazie {faza}, nie 'written' - "
                                          f"powrót odmawia", None)
        if repo.newer_inplace_op(con, location_id=loc["id"], op_id=op_id):
            return WriteResult("blocked", f"lokacja ma operację nowszą niż {op_id} - powrót "
                                          f"odmawia, żeby nie cofnąć późniejszego zapisu", None)
        st = os.fstat(fh.fileno())
        if st.st_size != spec.file_size or (spec.file_ino and st.st_ino
                                            and st.st_ino != spec.file_ino):
            return WriteResult("blocked", f"inny plik niż w chwili zapisu (rozmiar/st_ino); "
                                          f"{_RECZNA}", None)
        fh.seek(spec.region_offset)
        biezacy = fh.read(len(spec.new_region))
        if not _stan_posredni(biezacy, spec):
            return WriteResult("blocked", f"region nagłówka nie jest ani wynikiem operacji {op_id}, "
                                          f"ani stanem pośrednim jej powrotu; {_RECZNA}", None)
        if biezacy == spec.new_region:
            try:
                niezgodne = _kontrola_danych(path, scan.scan_file(path), loc["sha1_data"],
                                             kontrola)
            except Exception as exc:  # noqa: BLE001 - czkawka odczytu nie jest werdyktem
                return WriteResult("failed", f"odczyt kontrolny padł - {type(exc).__name__}: "
                                             f"{exc}; {ponow}", None)
            if niezgodne is None:
                return WriteResult("blocked", f"kontrola danych operacji {op_id} przechodzi - "
                                              f"zapis jest poprawny, powrót go nie cofa; dokończ: "
                                              f"finish_inplace({op_id})", None)
        else:
            niezgodne = "przerwany wcześniejszy powrót tej operacji"
        res = _odzysk_pod_blokada(fh, path, spec)
        if res.status != "applied":
            return WriteResult(res.status, f"{res.reason}; {ponow}", None)
        prawda = (f"plik zmienił się poza nagłówkiem od ostatniego skanu albo przy zapisie "
                  f"({niezgodne}) - zapis cofnięty: stary nagłówek przywrócony w miejscu "
                  f"(operacja {op_id}), przeskanuj plik")
        try:
            repo.revert_inplace_op(con, op_id=op_id, now=now, reason=prawda)
        except Exception as exc:  # noqa: BLE001
            return WriteResult("failed", f"stary nagłówek przywrócony, ale faza 'recovered' NIE "
                                         f"zapisana ({type(exc).__name__}: {exc}); {ponow}", None)
        return WriteResult("applied", prawda, None)
    wynik = _pod_blokada(path, _dzialanie)
    status = "restored" if wynik.status == "applied" else wynik.status
    return FileResult(loc["id"], path, status, wynik.reason)

