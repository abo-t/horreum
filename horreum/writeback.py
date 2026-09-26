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
2. ORKIESTRACJA (`commit`/`undo`): grupuje `pending_changes` po LOCATION, per plik zapisuje i
   RE-SYNCUJE bazę przez `scan.ingest_record(actor="user:local")` — REUŻYWA znanej-ścieżki skanu
   (SPOT, brief §3/R#2): `refresh_location` odświeża fakty kopii + zeznanie + WYMIANĘ `cards` +
   przelicza `frame.camera_id`/`kind` (`event(frame.rederived)`). Bespoke writer POMINĄŁBY rederive
   → config na stęchłej kamerze. KAŻDY re-sync emituje eventy (fakt domenowy = mutacja pliku);
   staging (backup/status/commit) jest transient, BEZ eventu (brief §3/R#1).

Kolejność PLIK→DB (brief T8): `os.replace` PIERWSZY, potem re-sync DB; crash pomiędzy → plik
zmieniony, DB stęchłe, kotwicą naprawy jest RE-SKAN (`header_hash` mismatch → refresh). Backup undo
zapisany PO udanym `os.replace`. Utrwalanie per plik (funkcje stagingu `repo` commitują od razu),
więc anulowanie na granicy pliku jest bezpieczne: pliki już zapisane zostają 'applied', reszta
'pending' (wznawialne).
"""

from __future__ import annotations

import dataclasses
import hashlib
import os
import re
import shutil
import sqlite3
import tempfile
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
    'blocked' i 'failed' sprzed podmiany mają oba pola `None` i plik bajtowo nietknięty."""
    status: str            # 'applied' | 'blocked' | 'failed'
    reason: str | None
    post_hash: str | None  # header_hash PO zapisie (z ZAPISANEGO pliku) — kontrola undo + kolejny zapis
    backup_text: str | None = None  # pełny nagłówek SPRZED zapisu (undo)


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


def write_changes(path, ops: list[WriteOp], expected_hash: str | None) -> WriteResult:
    """Atomowo zapisz zmiany w nagłówku wybranego HDU. Kontrola `header_hash`: nagłówek na dysku ≠
    `expected_hash` → 'blocked', NIE pisze. Treść łamiąca reguły karty FITS 4.0 (`card_violation`)
    → 'blocked' z powodem, NIE pisze - zamiast angielskiego wyjątku astropy albo cichego CONTINUE,
    ucięcia komentarza czy karty HIERARCH. Plik tymczasowy jest czytany PRZED podmianą (plik
    nieczytelny nie zastąpi oryginału), a jego hash jest kotwicą weryfikacji po podmianie
    (`_after_replace`). Zwraca `post_hash` z zapisanego pliku + `backup_text` (pełny nagłówek sprzed
    zmian → undo) - także przy 'failed' PO podmianie. Port dawcy `fits_io.write_changes`.
    `.xisf` → `write_xisf_changes` (inny format, TEN SAM kontrakt `WriteResult`).
    `.dng/.arw/.cr2` → ODMOWA (#2): RAW jest read-only (rename dozwolony osobno)."""
    if _is_raw(path):
        return WriteResult("blocked", "format RAW jest read-only (#2)", None)
    if _is_xisf(path):
        return write_xisf_changes(path, ops, expected_hash)
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
            backup_text = hdr.tostring()  # pełny nagłówek SPRZED zmian → undo
            for op in ops:
                _apply_op(hdr, op)
            fd, tmp = tempfile.mkstemp(suffix=".tmp", dir=os.path.dirname(os.path.abspath(path)))
            os.close(fd)
            hdul.writeto(tmp, overwrite=True)
        # Poza `with`: uchwyt oryginału zwolniony (Windows). Odczyt pliku tymczasowego TĄ SAMĄ
        # formułą co skan, zanim zastąpi oryginał: nieczytelny → 'failed' i oryginał nietknięty;
        # czytelny → hash tego, co za chwilę będzie na dysku (kotwica `_after_replace`).
        written_hash = scan.read_fits_meta(tmp).header_hash
        os.replace(tmp, path)
        tmp = None
    except Exception as exc:  # noqa: BLE001 — raport zamiast wyjątku w warstwie zapisu
        return WriteResult("failed", f"{type(exc).__name__}: {exc}", None)
    finally:
        if tmp is not None and os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
    return _after_replace(path, written_hash, backup_text)   # T3: hash z ZAPISANEGO pliku


def write_full_header(path, header_text: str, expected_hash: str | None) -> WriteResult:
    """Atomowo przepisz CAŁY nagłówek wybranego HDU z `header_text` (ścieżka undo). Kontrola
    `header_hash` jak w `write_changes` (dysk ≠ `expected_hash` → 'blocked'). `header_text` =
    wcześniejszy `hdr.tostring()`; odtwarzamy przez `Header.fromstring`. Dane nietknięte (zmienia
    się `file_sha1`, `sha1_data` zostaje). Port dawcy `fits_io.write_full_header`.
    `.xisf` → `write_xisf_full_header` (tam `header_text` = oryginalny XML).
    `.dng/.arw/.cr2` → ODMOWA (#2): RAW jest read-only."""
    if _is_raw(path):
        return WriteResult("blocked", "format RAW jest read-only (#2)", None)
    if _is_xisf(path):
        return write_xisf_full_header(path, header_text, expected_hash)
    path = os.fspath(path)
    tmp: str | None = None
    try:
        with fits.open(path, mode="readonly", memmap=False) as hdul:
            index, hdu = scan._select_hdu(hdul)
            current = scan._header_hash(hdu.header)
            if expected_hash is not None and current != expected_hash:
                return WriteResult("blocked", "header_hash mismatch", None)
            hdu.header = fits.Header.fromstring(header_text)
            fd, tmp = tempfile.mkstemp(suffix=".tmp", dir=os.path.dirname(os.path.abspath(path)))
            os.close(fd)
            hdul.writeto(tmp, overwrite=True)
        os.replace(tmp, path)
        tmp = None
        post = _post_hash(path)
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


def _write_xisf_file(path: str, region: bytes, tail_start: int) -> None:
    """Atomowa podmiana pliku XISF: temp w TYM SAMYM katalogu (ten sam wolumen → `os.replace` jest
    atomowy), nowy region nagłówka + OGON verbatim od pierwszego bloku danych. Kopiujemy cały plik
    — parytet z FITS, gdzie `hdul.writeto(tmp)` robi dokładnie to samo. Łata w miejscu (`r+b`) jest
    odrzucona: NIEATOMOWA, więc przerwa zostawiłaby uszkodzonego mastera."""
    tmp: str | None = None
    try:
        fd, tmp = tempfile.mkstemp(suffix=".tmp", dir=os.path.dirname(os.path.abspath(path)))
        os.close(fd)
        with open(path, "rb") as src, open(tmp, "wb") as dst:
            dst.write(region)
            src.seek(tail_start)
            shutil.copyfileobj(src, dst, 1 << 20)
        os.replace(tmp, path)          # poza `with`: uchwyty zwolnione (Windows) → podmiana
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


def write_xisf_changes(path, ops: list[WriteOp], expected_hash: str | None) -> WriteResult:
    """Łata bajtowa nagłówka XISF — bliźniak `write_changes` z tym samym kontraktem `WriteResult`.

    Kolejność (brief §5): odczyt → kontrola `header_hash` (≠ → 'blocked', NIE pisze) → bramki
    D-X-11/13 → REGUŁY KARTY (`card_violation`, spec §11.6) → lokalizacja i podmiana wycinków
    (karta + zmapowana własność + komentarz) → WERYFIKACJA nowego XML-a (`_xisf_verify`: §9.5
    i round-trip kart) → round-trip backupu (D-X-9) → BRAMKA MIESZCZENIA SIĘ (D-X-2) → temp +
    `os.replace` → weryfikacja po podmianie (`_after_replace`: `post_hash` z ZAPISANEGO pliku ==
    sha1 złożonego XML-a). `backup_text` = oryginalny XML (wejście `write_xisf_full_header` przy
    undo) - także przy 'failed' PO podmianie, bo wtedy plik jest już zmieniony.

    Odmowa ('blocked') zostawia plik bajtowo nietknięty — wszystkie bramki liczą się PRZED
    stworzeniem pliku tymczasowego. Awaria ('failed') to każdy inny wyjątek, w tym rozejście się
    skanu bajtowego z parserem (guard `locate_value_span`) i nieudana weryfikacja nowego XML-a: tam
    nie wiemy, co byśmy zapisali, więc nie piszemy, ale to usterka do zbadania, nie polityka odmowy."""
    path = os.fspath(path)
    try:
        meta = _read_xisf_or_refuse(path)
        if expected_hash is not None and meta.header_hash != expected_hash:
            return WriteResult("blocked", "header_hash mismatch", None)
        _xisf_gates(meta)
        powod = _ops_violation(ops, lambda op: op.op == "add")   # `set` nie zakłada karty (niżej)
        if powod is not None:
            raise _XisfRefusal(powod)
        patches = _xisf_patches(meta, ops)
        new_xml = _xisf_apply(meta.xml_bytes, patches)
        _xisf_verify(meta, ops, patches, new_xml)      # §9.5 + round-trip: PRZED plikiem tymczasowym
        backup_text = _xisf_backup_text(meta)          # D-X-9: PRZED mutacją, nie przy undo
        try:
            region = scan.build_xisf_header_region(meta, new_xml)      # D-X-1/2
        except ValueError as exc:                      # nie mieści się / plik przeczy sam sobie
            raise _XisfRefusal(str(exc)) from exc
        _write_xisf_file(path, region, meta.first_attachment)          # tu następuje os.replace
    except _XisfRefusal as ref:
        return WriteResult("blocked", ref.reason, None)
    except Exception as exc:  # noqa: BLE001 — raport zamiast wyjątku w warstwie zapisu
        return WriteResult("failed", f"{type(exc).__name__}: {exc}", None)
    # Header_hash XISF to sha1 bajtów XML (D-X-3), a pisarz zapisuje je 1:1 - więc hash tego, co
    # zapisaliśmy, znamy bez odczytu, a odczyt (T3) ma go tylko potwierdzić.
    return _after_replace(path, hashlib.sha1(new_xml).hexdigest(), backup_text)


def write_xisf_full_header(path, header_text: str, expected_hash: str | None) -> WriteResult:
    """Przepisz CAŁY nagłówek XISF z `header_text` (ścieżka undo, D-X-9) — bliźniak
    `write_full_header`. Ta sama kontrola `header_hash` (tu `post_hash` z backupu) i TA SAMA bramka
    mieszczenia się: undo skraca nagłówek, więc mieści się zawsze, ale bramki nie omijamy.
    Attachmenty nietknięte → `sha1_data` stoi.

    Wypełnienie po undo: bajty, które nadpisał dłuższy nagłówek, wracają jako ZERA (wskrzesić się
    ich nie da). Nagłówek wraca BAJTOWO — a że wypełnienie jest w archiwum zerowe (330/330 plików),
    w praktyce wraca bajtowo CAŁY plik, czego writeback FITS nie potrafi (astropy kanonizuje karty
    strukturalne przy `writeto`)."""
    path = os.fspath(path)
    try:
        meta = _read_xisf_or_refuse(path)
        if expected_hash is not None and meta.header_hash != expected_hash:
            return WriteResult("blocked", "header_hash mismatch", None)
        try:
            region = scan.build_xisf_header_region(meta, header_text.encode("utf-8"))
        except ValueError as exc:
            raise _XisfRefusal(str(exc)) from exc
        _write_xisf_file(path, region, meta.first_attachment)
        post = _post_hash(path)
    except _XisfRefusal as ref:
        return WriteResult("blocked", ref.reason, None)
    except Exception as exc:  # noqa: BLE001
        return WriteResult("failed", f"{type(exc).__name__}: {exc}", None)
    return WriteResult("applied", None, post, header_text)


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
    """Wiersz location potrzebny do zapisu: path, volume, header_hash, hdu_index, compressed, present."""
    return con.execute(
        "SELECT id, frame_id, volume, path, header_hash, hdu_index, compressed, present "
        "FROM location WHERE id = ?",
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


def _resync(con, path, volume, *, now, actor="user:local"):
    """RE-SYNC bazy po mutacji pliku — REUŻYWA znanej-ścieżki skanu (SPOT, R#2). `scan_file`
    (read-only, świeże hasze/nagłówek/karty) → `ingest_record`: `refresh_location` odświeża fakty
    kopii + zeznanie + `cards` + `frame.camera_id/kind` z eventami (actor="user:local"). Wymaga
    BRAKU otwartej transakcji (refresh bierze BEGIN IMMEDIATE) — funkcje stagingu `repo` commitują
    same, więc jest czysto."""
    rec = scan.scan_file(path)
    scan.ingest_record(con, rec, volume=volume, now=now, summary=scan.ScanSummary(), actor=actor)


def commit(con, run_id, *, now, clock=None,
           progress: Callable[[int, int, str, str], None] | None = None,
           should_cancel: Callable[[], bool] | None = None) -> CommitResult:
    """Zapisz `pending_changes` (status 'pending') przebiegu do plików. Grupuje po LOCATION, per plik:
    kontrola `header_hash` (kotwica `expected_header_hash` ze stagingu, R#7) → `write_changes`
    (`os.replace`) → backup + `post_hash` → RE-SYNC (`refresh_location` przez `ingest_record`) →
    status 'applied'. Utrwalanie per plik (funkcje `repo` commitują), więc anulowanie
    (`should_cancel` PRZED plikiem) zostawia zapisane 'applied', resztę 'pending'. `progress(done,
    total, path, status)` po KAŻDYM pliku. Callbacki Qt-wolne (GUI podaje je z wątku roboczego).

    Bramki defensywne (makro już odsiało przy stagingu, ale stan mógł się zmienić): brak location /
    `present=0` / `compressed` → skipped z powodem, wpisy 'skipped'. `clock` = źródło `applied_at`
    commitu (domyślnie `now`).

    PORAŻKA BACKUPU po udanym zapisie (D-X-14) → 'failed' z powodem, NIE wyjątek: plik jest już
    zmieniony, więc pętla musi go domknąć (re-sync + status), a nie zostawić przebiegu w połowie.

    WERYFIKACJA PO PODMIANIE PADŁA (`WriteResult` 'failed' z `backup_text`) → backup do
    `header_backups` jak przy 'applied' (undo commitu cofnie i ten plik), status 'failed' z powodem
    i numerem commitu, ale BEZ re-syncu i bez gaszenia nagrobka: bajtów na dysku nie potwierdzono,
    więc bazę naprawi re-skan (T8). Kryterium „plik podmieniony" to `backup_text is not None`, nie
    status - tak brzmi kontrakt `WriteResult`."""
    clock = clock or (lambda: now)
    pending = [r for r in pending_for_run(con, run_id) if r["status"] == "pending"]
    groups = _group_by_location(pending)
    total = len(groups)

    applied: list[FileResult] = []
    blocked: list[FileResult] = []
    failed: list[FileResult] = []
    skipped: list[FileResult] = []
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

        ops = [WriteOp(keyword=r["keyword"], op=r["op"], value=r["new_value"],
                       value_type=r["new_type"], idx=r["idx"], comment=r["new_comment"])
               for r in rows]
        expected = rows[0]["expected_header_hash"]  # kotwica stagingu (R#7)
        res = write_changes(path, ops, expected)  # tu następuje os.replace

        if res.backup_text is not None:   # plik PODMIENIONY: 'applied' albo 'failed' PO os.replace
            assert res.post_hash
            if commit_id is None:
                commit_id = repo.insert_commit(con, run_id=run_id, now=clock(),
                                               summary=f"run {run_id}")
            # Backup PO mutacji pliku — jego porażka NIE może wywalić pętli (D-X-14): plik jest już
            # zmieniony, więc wyjątek zostawiłby resztę przebiegu nietkniętą, a TEN plik bez re-syncu
            # i bez statusu. Zamiast tego: re-sync (baza MUSI opisywać bajty, które leżą na dysku)
            # + status 'failed' z powodem — „zapisane, ale nieodwracalne" jest faktem do zobaczenia,
            # nie do zgadnięcia. (`hdu_index` NULL dla XISF już nie wybucha — migracja 0007.)
            backup_error = None
            try:
                repo.insert_header_backup(
                    con, commit_id=commit_id, location_id=location_id, hdu_index=loc["hdu_index"],
                    header_text=res.backup_text, post_hash=res.post_hash)
            except sqlite3.Error as exc:
                backup_error = f"plik ZAPISANY, ale backup do undo NIE powstał: {type(exc).__name__}: {exc}"
            if res.status != "applied":
                # Weryfikacja PO podmianie padła (`_after_replace`): backup JEST, więc undo tego
                # commitu cofnie plik, o ile leży na nim dokładnie to, co zapisaliśmy (`post_hash`).
                # Re-syncu NIE robimy: baza opisuje bajty POTWIERDZONE, a tych nie potwierdziliśmy.
                # Odczyt albo padł - padłby i w `scan_file`, a jego miękkie lądowanie przy XISF nie
                # ma tożsamości (`sha1_data` z obrazu) i rozdwoiłoby klatkę - albo pokazał nie to,
                # co zapisaliśmy (ktoś pisał równolegle). Kotwicą naprawy zostaje re-skan (T8), tak
                # jak przy crashu między plikiem a bazą.
                # Nagrobek ręki też zostaje - gaśnie przy wpisanej karcie, a wpisu nie potwierdzono.
                reason = f"{res.reason}; backup do cofnięcia zapisany w commicie {commit_id}"
                if backup_error is not None:
                    reason = f"{res.reason}; {backup_error}"
                _mark(rows, "failed", reason)
                failed.append(FileResult(location_id, path, "failed", reason))
                _report(path, "failed")
                continue
            _resync(con, path, loc["volume"], now=now)      # PLIK→DB (T8)
            # NAGROBEK RĘKI GAŚNIE TU, a nie w ścieżce skanu (S2b, §4/14b-c). Klatka cofnięta ma
            # `object_source='user_cleared'` i drabina ją POMIJA — bez tego gestu zostałaby poza
            # osią na zawsze, nawet po dopisaniu karty. Wyzwalaczem jest WPISANIE `OBJECT` do TEGO
            # pliku, nie samo odświeżenie zeznania: klatka cofnięta MAJĄC już kartę ma zostać
            # cofnięta, dopóki człowiek tej karty nie zmieni — a każdy skan odświeża zeznanie i
            # gasiłby werdykt, którego nikt nie odwołał.
            if any(op.keyword == "OBJECT" for op in ops):
                repo.clear_object_tombstone(con, frame_id=loc["frame_id"], now=now)
            if backup_error is not None:
                _mark(rows, "failed", backup_error)
                failed.append(FileResult(location_id, path, "failed", backup_error))
                _report(path, "failed")
                continue
            _mark(rows, "applied", None)
            applied.append(FileResult(location_id, path, "applied"))
            _report(path, "applied")
        elif res.status == "blocked":
            _mark(rows, "blocked", res.reason)
            blocked.append(FileResult(location_id, path, "blocked", res.reason))
            _report(path, "blocked")
        else:
            _mark(rows, "failed", res.reason)
            failed.append(FileResult(location_id, path, "failed", res.reason))
            _report(path, "failed")

    return CommitResult(run_id, commit_id, applied, blocked, failed, skipped, cancelled)


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


def undo(con, commit_id, *, now,
         progress: Callable[[int, int, str, str], None] | None = None,
         should_cancel: Callable[[], bool] | None = None) -> UndoResult:
    """Cofnij commit: przepisz pełne nagłówki z `header_backups` (obsługuje set I add BEZ delete).
    Kontrola `header_hash` = `post_hash` z backupu (plik zmieniony od commitu → 'blocked'; dwukrotne
    undo naturalnie 'blocked'). Po udanym zapisie RE-SYNC bazy (refresh). `progress`/`should_cancel`
    jak w `commit` (per plik, granica bezpieczna)."""
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
        res = write_full_header(path, b["header_text"], b["post_hash"])
        if res.status == "applied":
            _resync(con, path, loc["volume"], now=now)
            restored.append(FileResult(loc["id"], path, "restored"))
            _report(path, "restored")
        elif res.status == "blocked":
            blocked.append(FileResult(loc["id"], path, "blocked", res.reason))
            _report(path, "blocked")
        else:
            failed.append(FileResult(loc["id"], path, "failed", res.reason))
            _report(path, "failed")

    return UndoResult(commit_id, restored, blocked, failed, cancelled)
