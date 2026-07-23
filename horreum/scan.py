"""Skan drzewa FITS + XISF — primitivy read-only + pętla płaska skanu (PLAN §4; §Etap 1/§Etap 4).

Per plik produkuje TOŻSAMOŚĆ + ZEZNANIE nagłówka, niczego nie zapisując:
  - odciski (przejście fitsmirror, brief §2 — port z dawcy `fits_io.py`):
      * `sha1_data` = sha1 sekcji DANYCH wybranego HDU (FITS) / bajtów attachmentu (XISF) —
        TOŻSAMOŚĆ frame'a (schemat v2): przeżywa edycję nagłówka/rename/move/writeback;
        nieobliczalny → degeneracja (sha1 całego pliku + flaga `sha1_data_uncomputable`),
      * `file_sha1` = sha1 całego pliku (fakt KOPII na location — detekcja zmiany bajtów);
        dla pliku nieskompresowanego OBA hasze liczone JEDNYM przebiegiem (`sha1_of_span` —
        pozycje sekcji z nagłówków przed odczytem treści),
      * `header_hash` = odcisk nagłówka (kontrola writeback/undo): FITS — sha1 tekstu nagłówka,
        XISF — sha1 bajtów XML (P6a),
      * `cards` = pełne lustro nagłówka (EAV: keyword/idx/value_raw/value_num/value_type/comment)
        — FITS z astropy, XISF z `<FITSKeyword>` (P6a; `value_type` zawsze `'str'`).
  - `read_header` (dyspozytor) = pełny nagłówek jako JSON-owalny dict:
      * FITS (.fits/.fit/.fts) → astropy, read-only,
      * XISF (.xisf) → lekki czytnik stdlib (`struct` + `xml.etree`), bez nowej zależności.
    To przyszłe `header.raw_json` + materiał dla pól gorących (§3.3/§3.5) — wyłuskanie należy do
    warstwy upsertu (krok §4.2). UWAGA W3: XISF zwraca wartości jako STRINGI; rzut na typ robią
    dopiero pola gorące (§Etap 2), nie ten moduł.
  - `header_dict_from_cards` (odwrotność `_parse_cards`) = synteza dict-a zeznania z kart —
    kontrakt IDENTYCZNY z `read_fits_header`; na niej stoi import z dawcy (PF-3, brief §4.2).

DOKTRYNA `.data` (R1#14): sięgnięcie po `hdul[i].data` (dekompresja pikseli) jest dozwolone
WYŁĄCZNIE dla CompImageHDU na potrzeby hasza tożsamości (`compressed_data_sha1`) — surowe bajty
sekcji danych mastera to skompresowana tabela kafelkowa, nieporównywalna między ustawieniami
kompresji. Każde inne użycie `.data` w tym module = błąd (nagłówki czytamy bez pikseli).

Żaden zapis nie idzie z tego modułu wprost: primitywy (`iter_*`/`read_*`/`scan_file`) są read-only,
a pętla `scan_tree` (§Etap 4) deleguje WSZYSTKIE zapisy do `repo` (jedna klinga) — scan.py nie
wykonuje żadnego DML (meta-tripwir AST to potwierdza). Nie zapisuje też na dysk usera (inwariant
append-only, PLAN §6): pliki otwierane WYŁĄCZNIE do odczytu. FITS przez astropy
`memmap=False` i bez sięgania po `.data`; XISF czyta tylko nagłówek (sygnatura + XML, bez bloków
danych) — więc na Windowsie nie zostaje uchwyt blokujący plik. `astropy` jest PIERWSZĄ zależnością
runtime Horreum (dochodzi z czytnikiem FITS); XISF korzysta wyłącznie ze stdlib.

Miękkie lądowanie (W1): `read_*` MOGĄ rzucać dla pliku nieczytelnego/nierozpoznanego — łapie to
`scan_file` (zwraca `ScanRecord(header=None, error=...)`, tożsamość degeneruje do `file_sha1`),
nie pętla ani użytkownik. Nierozstrzygalność trafia do `event(*.review)` w warstwie upsertu.

TOŻSAMOŚĆ ŚCIEŻEK = FORMA LITEROWA (brief §0, ŚWIĘTE od R2): ZAKAZ `os.path.realpath`/
`Path.resolve` w torze tożsamości — na zamapowanym `R:` rozwiązują do UNC (`\\\\NAS\\...`), co
rozdwaja lokacje przy tym samym `volume_serial`. Kanonizacja roota = jawna sekwencja
`canonize_root` (R3-a1); guard UNC odmawia rootów `\\\\host\\share` (R3-a2).
"""
import ctypes
import hashlib
import json
import math
import os
import re
import struct
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from astropy.io import fits

from . import exif, repo
from .hashing import sha1_of, sha1_of_span
from .resolve.cameras import camera_identity
from .resolve.frames import kind_from_path, normalize_kind
from .resolve.headers import extract_header

# Rozszerzenia nagłówkonośne (PLAN §1.1: jeden mechanizm, format = opakowanie). DSLR/RAW
# (.dng/.arw/.cr2, czytnik EXIF `exif.py`) DOŁĄCZONY do JEDNEGO passa skanu (#2, D-R-3 —
# ratyfikacja Zdzinia 2026-07-23; ODWRACA dawne „drugi przebieg" z PLAN §1.5): osobny MODUŁ
# czytnika, ale WSPÓLNY `ingest_record`/tożsamość/brama przyrostowa/wykluczenia (anty-SIN-DUP).
# Dyspozycja po SUFIKSIE (`read_header`/`scan_file`/`_filetype`).
FITS_SUFFIXES = (".fits", ".fit", ".fts")
XISF_SUFFIXES = (".xisf",)
HEADER_SUFFIXES = FITS_SUFFIXES + XISF_SUFFIXES + exif.RAW_SUFFIXES

# Słowa-klucze nagłówkowe powtarzalne (komentarze/historia/puste) — akumulujemy w listę, żeby
# zeznanie było 1:1 (nie gubimy powtórzeń przez kolizję klucza w dict). Wspólne FITS↔XISF.
_MULTI_KEYWORDS = ("COMMENT", "HISTORY", "")

_XISF_SIGNATURE = b"XISF0100"        # monolithic XISF 1.0; po nim uint32 LE = długość nagłówka XML
_XISF_LENGTH_LEN = 4                 # uint32 LE — długość nagłówka XML
_XISF_RESERVED_LEN = 4               # 4 B reserved (wg specyfikacji zerowe; kopiowane verbatim)

# Bajt, na którym ZACZYNA SIĘ nagłówek XML. WYLICZONY, nigdy literał (P6/§0): pomyłka o 4 B przy
# zapisie nadpisuje pierwszy blok danych mastera. JEDNO źródło dla czytnika i pisarza XISF.
XISF_XML_OFFSET = len(_XISF_SIGNATURE) + _XISF_LENGTH_LEN + _XISF_RESERVED_LEN     # == 16

# Katalogi-drzewa robocze wykluczane ze skanu (doktryna README §„baza = autorytet": projekcje WBPP
# to wyjście z bazy, nie wejście). JAWNA LISTA, nie konwencja `_*` — firsthand na realnym drzewie pokazał
# realne `_COMETS`/`_SOLAR` pod LIGHTS\ (1197 lightów), które konwencja porzuciłaby. Dopasowanie
# NIEWRAŻLIWE na wielkość (NTFS; realne nazwy to `_WBPP`/`_REVIEW`). Trzymamy w lowercase.
EXCLUDED_DIR_NAMES = frozenset({"_wbpp", "_review"})


@dataclass(frozen=True)
class Card:
    """Pojedyncza karta nagłówka w postaci wierszowej (jak wiersz tabeli `cards`; port 1:1 z dawcy
    `fits_io.Card`). `idx` = kolejność wystąpienia danego keyworda w HDU (wiernie zachowuje
    duplikaty: COMMENT/HISTORY i powtórzone keywordy). `value_num` tylko dla int/float —
    porównania numeryczne idą po nim, tekstowe po `value_raw`."""
    keyword: str
    idx: int
    value_raw: object                 # str | None
    value_num: object                 # float | None
    value_type: str                   # int | float | str | bool | undefined
    comment: object                   # str | None


@dataclass(frozen=True)
class ScanRecord:
    """Wynik skanu jednego pliku (read-only). Materiał wejściowy dla upsertu frame/location/header
    (krok §4.2) — sam w sobie nie jest zapisem domenowym.

    `header is None` + `error` ustawione = plik nieczytelny/nierozpoznany (miękkie lądowanie W1):
    namiary (`path`/`size`/`mtime`) i `file_sha1` są, lecz nagłówka/odcisków sekcji brak →
    degeneracja tożsamości + review wyżej.

    Odciski (brief §2):
      - `sha1_data`: sha1 sekcji DANYCH HDU (FITS) / bajtów attachmentu (XISF) — TOŻSAMOŚĆ
        frame'a; None = nieobliczalne (brak sekcji danych / zepsuty kafelek / W1) → degeneracja
        w `ingest_record` (sha1 pliku + flaga `sha1_data_uncomputable`);
      - `file_sha1`: sha1 całego pliku (fakt KOPII na location — detekcja zmiany bajtów);
      - `header_hash`: odcisk nagłówka (kontrola writeback/undo) — FITS: sha1 tekstu nagłówka,
        XISF: sha1 bajtów XML (P6a/D-X-3); None przy W1;
      - `hdu_index`/`compressed`: fakty kopii FITS; None dla XISF (D-X-7 — pojęcia obce formatowi)
        i przy W1;
      - `cards`: pełne lustro nagłówka (lista `Card`) — FITS z astropy, XISF z `<FITSKeyword>`
        (P6a/D-X-4); None przy W1.
    """
    path: str                         # ścieżka bezwzględna (str — spójnie z sha1_of/repo)
    size_bytes: int                   # fakt kopii (→ location.size_bytes; R2#6)
    mtime: str                        # ISO-8601 UTC (brama przyrostowa)
    header: dict = field(default_factory=dict)   # pełny nagłówek, JSON-owalny; None gdy error
    error: object = None              # None gdy OK; tekst "Typ: opis" gdy nagłówek nieczytelny (W1)
    sha1_data: object = None          # tożsamość frame'a; None = nieobliczalne (degeneracja wyżej)
    file_sha1: object = None          # sha1 całego pliku (fakt kopii)
    header_hash: object = None        # sha1 tekstu nagłówka; None dla XISF/W1
    hdu_index: object = None          # HDU naukowe; None dla XISF/W1
    compressed: object = None         # 0/1 (CompImageHDU); None dla XISF/W1
    cards: object = None              # list[Card] — lustro nagłówka; None dla XISF/W1


def _iter_suffixes(root, suffixes, excluded_out=None, errors_out=None):
    """Przejdź drzewo `root` i wydaj POSORTOWANE ścieżki plików o danych rozszerzeniach
    (case-insensitive). Zwraca `Path`; pomija katalogi i inne rozszerzenia. Czysty odczyt katalogu.

    WYKLUCZANIE DRZEW ROBOCZYCH (doktryna README §„baza = autorytet"): podkatalog o nazwie z JAWNEJ
    listy `EXCLUDED_DIR_NAMES` (`_WBPP`, `_Review`; niewrażliwie na wielkość) jest ODCINANY — skaner
    do niego NIE SCHODZI (a nie tylko filtruje pliki). To egzekwuje regułę „drzewa WBPP to jednorazowe
    projekcje z bazy, nie wejście skanu". NIE konwencja `_*`: firsthand pokazał realne `_COMETS`/
    `_SOLAR` (lighty), które konwencja porzuciłaby. WYJĄTEK: jawnie wskazany root (`os.walk` zaczyna
    OD niego, filtr `dirnames` nie tyka punktu startu) — gdy user świadomie wskaże `…\\_WBPP`, skanujemy
    go normalnie. `os.walk` domyślnie NIE podąża za symlinkami (`followlinks=False`) — drugi wektor
    wciągania projekcji odcięty.

    `excluded_out` (opcjonalna lista): jeśli podana, dopisujemy do niej ŚCIEŻKI wykluczonych
    katalogów — nie chowamy faktu wykluczenia za samym licznikiem (diagnostyka: user widzi, czego
    skan nie wciągnął). `os.walk` daje kolejność systemową → finalne `sorted(...)` trzyma kontrakt
    „POSORTOWANE" (jak dawne `rglob`+`sorted`).

    `errors_out` (opcjonalna lista, P5/D-V-11): ścieżki katalogów, których `os.walk` NIE PRZECZYTAŁ
    (brak uprawnień, zerwany SMB). Domyślnie `os.walk` POŁYKA te błędy — dla SKANU to łagodne (pliki
    wejdą następnym razem), ale dla passa obecności KORUMPUJĄCE: każdy wiersz DB pod nieprzeczytanym
    katalogiem wyglądałby na zniknięty. Wołający, który podaje tę listę, MUSI traktować poddrzewa
    z błędem dokładnie jak prune (poza oceną), nie jak brak plików."""
    root = Path(root)
    out = []

    def _on_error(exc):                                    # os.walk woła z OSError (ma .filename)
        if errors_out is not None:
            errors_out.append(getattr(exc, "filename", None) or str(exc))

    for dirpath, dirnames, filenames in os.walk(root, onerror=_on_error):   # followlinks=False — bez symlinków
        excl = [d for d in dirnames if d.lower() in EXCLUDED_DIR_NAMES]
        if excluded_out is not None:
            excluded_out.extend(str(Path(dirpath) / d) for d in excl)
        dirnames[:] = sorted(d for d in dirnames if d.lower() not in EXCLUDED_DIR_NAMES)  # prune + determinizm
        for name in filenames:
            p = Path(dirpath) / name
            if p.suffix.lower() in suffixes:
                out.append(p)
    return sorted(out)                                     # kontrakt: POSORTOWANE po ścieżce


def iter_fits(root):
    """Posortowane ścieżki plików FITS (.fits/.fit/.fts, case-insensitive) w drzewie `root`.
    Prymityw FITS-only; pełny skan pierwszego przebiegu używa `iter_headers` (FITS + XISF)."""
    return _iter_suffixes(root, FITS_SUFFIXES)


def iter_headers(root, excluded_out=None, errors_out=None):
    """Posortowane ścieżki WSZYSTKICH plików nagłówkonośnych pierwszego przebiegu (FITS + XISF,
    case-insensitive) w drzewie `root`. Wejście pętli płaskiej skanu (§Etap 4) I passa obecności
    (P5): jeden mechanizm, format = opakowanie (PLAN §1.1). Podkatalogi z `EXCLUDED_DIR_NAMES`
    odcięte (patrz `_iter_suffixes`); `excluded_out` zbiera ich ścieżki do telemetrii skanu,
    `errors_out` — katalogi NIEPRZECZYTANE (D-V-11; pass obecności traktuje je jak prune)."""
    return _iter_suffixes(root, HEADER_SUFFIXES, excluded_out=excluded_out, errors_out=errors_out)


def _jsonable(value):
    """Sprowadź wartość karty FITS do typu JSON-owalnego. astropy zwraca bool/int/float/str
    oraz `Undefined` dla kart bez wartości — to ostatnie mapujemy na None."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, fits.Undefined):
        return None
    return str(value)                 # cokolwiek egzotycznego (np. complex) → tekst, byle wiernie


def _put(out, keyword, value):
    """Dołóż kartę do dict zeznania (wspólna derywacja FITS↔XISF). COMMENT/HISTORY/puste akumuluj
    w listę (1:1, bez gubienia powtórzeń przez kolizję klucza); resztę zapisz wprost."""
    if keyword in _MULTI_KEYWORDS:
        out.setdefault(keyword or "_BLANK", []).append(value)
    else:
        out[keyword] = value


def _select_hdu(hdul):
    """Wybierz HDU niosące metadane akwizycji: pierwszy HDU z `NAXIS`>0 — zwykle PrimaryHDU;
    dla skompresowanych masterów (CompImageHDU) primary bywa pusty (NAXIS=0) — wtedy pierwsze
    HDU z obrazem; gdy żadnego (degeneracja) → Primary. Czytamy tylko nagłówki (NAXIS), nie
    ładując pikseli. Zwraca `(index, hdu)` — index idzie do `hdu_index`/`fileinfo` (port 1:1
    z dawcy `fits_io._select_hdu`)."""
    for i, hdu in enumerate(hdul):
        if hdu.header.get("NAXIS", 0):
            return i, hdu
    return 0, hdul[0]                 # awaryjnie: primary, choćby bez danych


def _header_to_dict(hdr):
    """Nagłówek astropy → JSON-owalny dict (zeznanie 1:1). Powtarzalne COMMENT/HISTORY/puste
    akumulowane w listę, by nie zgubić wierszy przez kolizję klucza."""
    out = {}
    for card in hdr.cards:
        kw = card.keyword
        value = str(card.value) if kw in _MULTI_KEYWORDS else _jsonable(card.value)
        _put(out, kw, value)
    return out


def _classify(value):
    """`(value_type, value_raw, value_num)` karty — port 1:1 z dawcy `fits_io._classify`.
    bool sprawdzany PRZED int (w Pythonie bool < int). int: `value_raw=str(v)` (bezstratnie,
    dowolna precyzja), float: `value_raw=repr(v)` (round-trip); `value_num` tylko dla liczb."""
    if value is None or isinstance(value, fits.Undefined):
        return "undefined", None, None
    if isinstance(value, bool):
        return "bool", ("T" if value else "F"), None
    if isinstance(value, int):
        return "int", str(value), float(value)
    if isinstance(value, float):
        return "float", repr(value), float(value)
    if isinstance(value, str):
        return "str", value, None
    return "str", str(value), None    # complex i inne egzotyki → tekst


def _parse_cards(hdr):
    """Nagłówek astropy → lista `Card` (pełne lustro EAV; port 1:1 z dawcy `fits_io._parse_cards`).
    `idx` numeruje wystąpienia KAŻDEGO keyworda od 0 — duplikaty (COMMENT/HISTORY i powtórzone
    keywordy zwykłe) zachowane wiernie."""
    counts = {}
    out = []
    for card in hdr.cards:
        kw = card.keyword
        idx = counts.get(kw, 0)
        counts[kw] = idx + 1
        vtype, vraw, vnum = _classify(card.value)
        out.append(Card(kw, idx, vraw, vnum, vtype, card.comment or None))
    return out


def _card_value(card):
    """Wartość natywna karty z postaci wierszowej — odwrotność `_classify` (brief §4.2):
    int z `value_raw` (BEZSTRATNIE — `value_num` REAL gubi wielkie inty, R1#8), float z
    `value_num`, bool `'T'`→True, undefined→None, str verbatim."""
    if card.value_type == "int":
        return int(card.value_raw)
    if card.value_type == "float":
        return card.value_num
    if card.value_type == "bool":
        return card.value_raw == "T"
    if card.value_type == "undefined":
        return None
    return card.value_raw


def header_dict_from_cards(cards):
    """Synteza dict-a zeznania z kart (odwrotność `_parse_cards`) — kontrakt IDENTYCZNY z
    `read_fits_header` tego samego nagłówka (na tym stoi import z dawcy, PF-3 / brief §4.2):
    COMMENT/HISTORY/puste keywordy po `idx` w listy (`_BLANK` dla pustych — przez wspólny `_put`),
    powtórzony keyword nie-multi → wygrywa NAJWYŻSZY idx (kontrakt `_put`: ostatni nadpisuje,
    R2#10). Kolejność dokumentowa kart NIE jest potrzebna: sort po `idx` ustawia listy i zwycięzcę
    per keyword, a dict nie zależy od przeplotu keywordów."""
    out = {}
    for c in sorted(cards, key=lambda c: c.idx):
        value = _card_value(c)
        _put(out, c.keyword, str(value) if c.keyword in _MULTI_KEYWORDS else value)
    return out


def _header_hash(hdr):
    """sha1 tekstu nagłówka (port 1:1 z dawcy `fits_io._header_hash`). Nagłówek FITS jest ASCII
    (wielokrotność 2880 znaków); latin-1 nigdy nie rzuca."""
    return hashlib.sha1(hdr.tostring().encode("latin-1", "replace")).hexdigest()


@dataclass(frozen=True)
class FitsMeta:
    """Komplet zeznania + odcisków nagłówka z JEDNEGO otwarcia astropy (`read_fits_meta`).
    `datloc`/`datspan` = pozycja/rozmiar sekcji danych wybranego HDU (z `fileinfo`, bez pikseli) —
    wejście `sha1_of_span` (hash danych i pliku jednym przebiegiem)."""
    header: dict
    cards: list
    header_hash: str
    hdu_index: int
    compressed: int                   # 0/1 (CompImageHDU)
    datloc: int
    datspan: int


def read_fits_meta(path):
    """Odczytaj z pliku FITS komplet: dict zeznania + karty + `header_hash` + `hdu_index` +
    `compressed` + pozycję sekcji danych — JEDNO otwarcie astropy, read-only, bez ładowania
    pikseli, bez pozostawiania uchwytu (Windows). Podnosi wyjątek dla pliku, który nie jest
    FITS — faza skanu nie zgaduje (nierozstrzygalność → `event(*.review)` w warstwie upsertu)."""
    with fits.open(path, mode="readonly", memmap=False) as hdul:
        index, hdu = _select_hdu(hdul)
        hdr = hdu.header
        info = hdul.fileinfo(index)
        return FitsMeta(
            header=_header_to_dict(hdr), cards=_parse_cards(hdr), header_hash=_header_hash(hdr),
            hdu_index=index, compressed=1 if isinstance(hdu, fits.CompImageHDU) else 0,
            datloc=info["datLoc"], datspan=info["datSpan"])


def read_fits_header(path):
    """Odczytaj nagłówek FITS jako JSON-owalny dict (kontrakt sprzed PF-1 bez zmian; dziś
    cienka nakładka na `read_fits_meta`)."""
    return read_fits_meta(path).header


def compressed_data_sha1(path, hdu_index):
    """sha1 SUROWYCH zdekompresowanych pikseli skompresowanego mastera (CompImageHDU) — port 1:1
    z dawcy `fits_io.compressed_data_sha1`.

    Po co osobno od hasza sekcji danych: sekcja danych mastera na dysku to skompresowana tabela
    kafelkowa — różna przy różnej kompresji nawet dla identycznych pikseli. Żeby master wszedł do
    grupowania po danych, hashujemy ZDEKOMPRESOWANĄ tablicę (jedyne sankcjonowane `.data` — patrz
    doktryna w nagłówku modułu, R1#14).

    Kontrakt postaci kanonicznej (deterministyczny między uruchomieniami i maszynami):
    `b"compdata|" + dtype.str(big-endian) + b"|" + "x".join(shape) + b"|" + bajty`, gdzie bajty to
    `ascontiguousarray(data.astype(big-endian))` (astype PIERW → realna zamiana bajtów, potem
    C-order). Otwieramy z `do_not_scale_image_data=True`: hash liczony na SUROWYCH stored pikselach
    (BZERO/BSCALE NIE stosowane) → niezależny od nagłówka i bez ryzyka MaskedArray od `BLANK`.
    Prefiks `compdata|` namespace'uje hash mastera — strukturalnie nie zderzy się z haszem sekcji.

    GRANICA: NIEporównywalny z haszem sekcji danych pliku nieskompresowanego (różne postaci) —
    grupowanie działa master-z-masterem, cross-format poza zakresem.

    Read-only, bez locków (`memmap=False`). `hdu_index` MUSI być tym wybranym przez `_select_hdu`.
    None gdy HDU nie ma danych; wyjątek uszkodzonego kafelka propaguje (soft-landing u wołającego)."""
    with fits.open(path, mode="readonly", memmap=False, do_not_scale_image_data=True) as hdul:
        data = hdul[hdu_index].data   # leniwe → dostęp WYZWALA dekompresję
        if data is None:
            return None
        be = np.ascontiguousarray(data.astype(data.dtype.newbyteorder(">")))
        prefix = (
            b"compdata|" + be.dtype.str.encode("ascii") + b"|"
            + "x".join(map(str, be.shape)).encode("ascii") + b"|"
        )
        digest = hashlib.sha1(prefix + be.tobytes()).hexdigest()
    return digest


def _local_name(tag):
    """Lokalna nazwa znacznika XML bez przestrzeni nazw (`{ns}FITSKeyword` → `FITSKeyword`).
    PixInsight osadza nagłówek w `xmlns='http://www.pixinsight.com/xisf'`; dopasowanie po nazwie
    lokalnej jest odporne na obecność/wariant namespace (xml.etree przykleja `{ns}` do tagu)."""
    return tag.rsplit("}", 1)[-1]


def _unquote_fits(value):
    """Zdejmij FITS-owe cudzysłowy z wartości stringowej XISF (firsthand: PixInsight zapisuje karty
    stringowe jak FITS — `'ZWO ASI2600MC Pro'`). Apostrofy obejmujące zdejmowane, `''`→`'` (escape
    FITS), końcowe spacje → rstrip (nieznaczący pad FITS). Dzięki temu dict jest 1:1 z
    `read_fits_header` (astropy też zwraca string bez apostrofów). Liczby/bool (bez apostrofów)
    zostają NIETKNIĘTE — rzut na typ i tak robi `_to_float` (pola gorące, W3)."""
    if isinstance(value, str) and len(value) >= 2 and value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'").rstrip()
    return value


def quote_fits(value, original):
    """Zakoduj wartość karty XISF do BAJTÓW łaty — odwrotność `_unquote_fits` (P6/D-X-6; w briefie
    `_quote_fits`). Konwencji NIE wymyślamy: przejmujemy ją z ORYGINAŁU (`original` = surowe bajty
    wartości sprzed zmiany, BEZ cudzysłowów XML).

    Zmierzone na 37 187 kartach z 331 realnych plików (sonda #4, 2026-07-22): apostrofy FITS
    w 4765 wartościach, 32 422 gołe, ZERO paddingu spacjami, ZERO podwojonych apostrofów, ZERO
    escape'ów XML, atrybut zawsze w cudzysłowie `"`. Stąd reguła: było w apostrofach → piszemy
    w apostrofach (z podwojeniem apostrofu wewnątrz — escape FITS); było gołe → piszemy gołe.
    **Paddingu spacjami NIE dokładamy** — w tym archiwum go nie ma, a dokładanie łamałoby zapis
    tożsamościowy (kryterium §6 pkt 1: przepisanie wartości AKTUALNEJ nie zmienia ani bajtu).

    Escape XML: `&` `<` `"`. **`>` zostaje surowy** — jest legalny wewnątrz wartości atrybutu,
    a escape'owanie go zmieniłoby bajty pliku, który go niesie."""
    text = str(value)
    if len(original) >= 2 and original.startswith(b"'") and original.endswith(b"'"):
        text = "'" + text.replace("'", "''") + "'"
    return _escape_xml(text, attribute=True).encode("utf-8")


def encode_xisf_value(value, xml_bytes, span):
    """Zakoduj SUROWĄ wartość do bajtów łaty — dla wycinków, które NIE są wartością karty:
    `<Property>` (D-X-10) i atrybut `comment` (D-X-12). Sam escape XML, BEZ konwencji FITS:
    apostrofy obejmujące to cecha KART (`quote_fits`), własność ich nie nosi.

    Kontekst escape'u czytany z bajtu PRZED wycinkiem — `locate_value_span` zwraca albo wnętrze
    cudzysłowu atrybutu, albo tekst elementu po `>`, więc trzeciej możliwości nie ma. Dzięki temu
    wołający nie może podać kontekstu SPRZECZNEGO z wycinkiem (a `"` escape'ujemy wyłącznie
    w atrybucie — w tekście elementu jest legalny surowy i escape zmieniłby bajty)."""
    in_attribute = xml_bytes[span[0] - 1:span[0]] in (b'"', b"'")
    return _escape_xml(str(value), attribute=in_attribute).encode("utf-8")


def _escape_xml(text, *, attribute):
    """Escape XML dla wartości wstawianej do łaty. `&` MUSI iść pierwszy (inaczej podwójny escape).
    `"` tylko w atrybucie (w tekście elementu jest legalny surowy, a escape zmieniłby bajty)."""
    out = text.replace("&", "&amp;").replace("<", "&lt;")
    return out.replace('"', "&quot;") if attribute else out


def _unescape_xml(text):
    """Odwrotność `_escape_xml` — do GUARDA zgodności z parserem, nie do zeznania. `&amp;` na
    KOŃCU (inaczej `&amp;lt;` rozwinąłby się dwa razy). Referencji liczbowych (`&#10;`) świadomie
    NIE rozwijamy: w archiwum jest ich zero (sonda #4), a gdyby się pojawiły, guard ma KRZYCZEĆ
    niezgodnością, nie zgadywać."""
    for ent, ch in (("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&apos;", "'")):
        text = text.replace(ent, ch)
    return text.replace("&amp;", "&")


_XISF_TAG_NAME = re.compile(rb"<\s*/?\s*([A-Za-z_:][\w:.\-]*)")
_XISF_ATTR = re.compile(rb"""([A-Za-z_:][\w:.\-]*)\s*=\s*("[^"]*"|'[^']*')""")


def _iter_xml_tags(xml_bytes):
    """Kolejne znaczniki `<…>` jako `(start, end)` — skan RESPEKTUJĄCY CUDZYSŁOWY: `>` wewnątrz
    wartości atrybutu jest legalny i NIE kończy znacznika, więc `find(b'>')` tu nie wystarcza
    (P6/#13). Komentarze i CDATA przeskakiwane po ich własnych terminatorach — one też mogą
    nieść `>`. Znacznik bez domknięcia → `ValueError` (EXPECT: nie zgadujemy granicy)."""
    i, n = 0, len(xml_bytes)
    while True:
        i = xml_bytes.find(b"<", i)
        if i < 0:
            return
        for opener, closer in ((b"<!--", b"-->"), (b"<![CDATA[", b"]]>")):
            if xml_bytes.startswith(opener, i):
                end = xml_bytes.find(closer, i + len(opener))
                if end < 0:
                    raise ValueError(f"XISF: niedomknięte {opener.decode()} w nagłówku")
                i = end + len(closer)
                break
        else:
            j, quote = i + 1, None
            while j < n:
                c = xml_bytes[j:j + 1]
                if quote is not None:
                    if c == quote:
                        quote = None
                elif c in (b'"', b"'"):
                    quote = c
                elif c == b">":
                    break
                j += 1
            if j >= n:
                raise ValueError("XISF: znacznik bez domknięcia '>'")
            yield i, j + 1
            i = j + 1


def _tag_attrs(tag_bytes):
    """Atrybuty znacznika jako `nazwa_lokalna -> (start, end)` bajtów WARTOŚCI (bez cudzysłowów),
    liczone względem początku znacznika."""
    out = {}
    for m in _XISF_ATTR.finditer(tag_bytes):
        start, end = m.span(2)
        out.setdefault(m.group(1).rsplit(b":", 1)[-1], (start + 1, end - 1))
    return out


class XisfTargetMissing(ValueError):
    """Adresu NIE MA w nagłówku (karta / atrybut / własność). Osobny typ, bo wołający reaguje na to
    RÓŻNIE zależnie od adresu: brak KARTY do zapisu = odmowa (dokładanie kart to D-X-12), brak
    zmapowanej WŁASNOŚCI = świadome pominięcie (D-X-10 — plik, który jej nigdy nie miał, nie jest
    sam ze sobą sprzeczny). Rozróżnianie po treści komunikatu byłoby kruche."""


class XisfValueUnreachable(ValueError):
    """Adres ISTNIEJE, ale jego wartość nie leży w nagłówku do przepisania: `location=`
    (inline/attachment) albo element pusty. Wołający mapuje na `blocked` — cel jest realny, więc
    ciche pominięcie zostawiłoby plik SPRZECZNY, a łata nagłówka nie ma tu czego chwycić."""


def locate_value_span(xml_bytes, *, keyword=None, idx=0, property_id=None, attr="value"):
    """Wycinek `[start, end)` bajtów WARTOŚCI w nagłówku XISF — materiał łaty (P6/§5).

    Adresowanie: `keyword`+`idx` (karta `<FITSKeyword>`, `idx` = numer wystąpienia keyworda
    w kolejności dokumentu) ALBO `property_id` (`<Property id=…>`). Dokładnie jedno z dwojga.
    `attr` wybiera atrybut karty — `value` (domyślnie) albo `comment` (D-X-12: komentarz łatamy
    TĄ SAMĄ techniką); przy adresowaniu własności nie ma sensu i jest odrzucany.

    Trzy postaci wartości (D-X-10, zmierzone na 7/7 celach): atrybut `value=` · TEKST elementu
    (`>ED<`) · `location=` (inline/attachment) → **`XisfValueUnreachable`**. Adres nieobecny →
    **`XisfTargetMissing`**. Oba są `ValueError` — wołający łapiący szeroko nic nie traci.

    GUARD EXPECT: wyłuskane bajty po odescape'owaniu MUSZĄ się zgadzać z wartością, którą z tego
    samego nagłówka wyjmuje parser XML. To CELOWO druga, niezależna derywacja — skan bajtowy
    i `ElementTree` liczą to samo dwiema drogami i muszą się spotkać. Rozejście → `ValueError`,
    NIGDY cichy zgadunek (łata trafiłaby w niewłaściwe bajty)."""
    if (keyword is None) == (property_id is None):
        raise ValueError("locate_value_span: podaj DOKŁADNIE jedno z keyword / property_id")
    if property_id is not None and attr != "value":
        raise ValueError("locate_value_span: `attr` dotyczy wyłącznie kart (<FITSKeyword>)")

    want = keyword.strip().upper() if keyword is not None else None
    want_attr = attr.encode("ascii")
    seen = 0
    for start, end in _iter_xml_tags(xml_bytes):
        tag = xml_bytes[start:end]
        m = _XISF_TAG_NAME.match(tag)
        if m is None or tag.startswith(b"</"):
            continue
        local = m.group(1).rsplit(b":", 1)[-1]
        attrs = _tag_attrs(tag)

        if want is not None:
            if local != b"FITSKeyword" or b"name" not in attrs:
                continue
            ns, ne = attrs[b"name"]
            name = _unescape_xml(tag[ns:ne].decode("utf-8"))
            if not name or name.strip().upper() != want:
                continue
            if seen != idx:
                seen += 1
                continue
            if want_attr not in attrs:
                raise XisfTargetMissing(f"XISF: karta {want}[{idx}] bez atrybutu {attr}=")
            vs, ve = attrs[want_attr]
            span = (start + vs, start + ve)
            break

        if local != b"Property" or b"id" not in attrs:
            continue
        ids, ide = attrs[b"id"]
        if _unescape_xml(tag[ids:ide].decode("utf-8")) != property_id:
            continue
        if b"location" in attrs:
            raise XisfValueUnreachable(
                f"XISF: własność {property_id} trzyma wartość w location= — poza nagłówkiem")
        if b"value" in attrs:
            vs, ve = attrs[b"value"]
            span = (start + vs, start + ve)
            break
        if tag.rstrip().endswith(b"/>"):
            raise XisfValueUnreachable(
                f"XISF: własność {property_id} pusta (element samozamykający)")
        text_end = xml_bytes.find(b"<", end)
        if text_end < 0:
            raise ValueError(f"XISF: własność {property_id} bez domknięcia elementu")
        span = (end, text_end)
        break
    else:
        cel = f"karta {want}[{idx}]" if want is not None else f"własność {property_id}"
        raise XisfTargetMissing(f"XISF: {cel} nieobecna w nagłówku")

    _assert_span_zgodny_z_parserem(xml_bytes, span, keyword=want, idx=idx,
                                   property_id=property_id, attr=attr)
    return span


def _assert_span_zgodny_z_parserem(xml_bytes, span, *, keyword, idx, property_id, attr="value"):
    """GUARD do `locate_value_span`: to samo pytanie zadane `ElementTree`. Dwie derywacje muszą dać
    ten sam tekst — inaczej łata pisałaby w niewłaściwe miejsce."""
    root = ET.fromstring(xml_bytes)
    expected = None
    if keyword is not None:
        seen = 0
        for elem in root.iter():
            if _local_name(elem.tag) != "FITSKeyword":
                continue
            name = elem.get("name")
            if not name or name.strip().upper() != keyword:
                continue
            if seen == idx:
                expected = elem.get(attr, "")
                break
            seen += 1
    else:
        for elem in root.iter():
            if _local_name(elem.tag) == "Property" and elem.get("id") == property_id:
                expected = elem.get("value") if elem.get("value") is not None else (elem.text or "")
                break
    actual = _unescape_xml(xml_bytes[span[0]:span[1]].decode("utf-8"))
    if actual != expected:
        cel = f"karta {keyword}[{idx}]" if keyword is not None else f"własność {property_id}"
        raise ValueError(
            f"XISF: skan bajtowy i parser rozeszły się na {cel} ({actual!r} != {expected!r})")


def _xisf_value_num(text):
    """`value_num` karty XISF = PROJEKCJA liczbowa tekstu (D-X-4), nie zmiana typu: `value_type`
    zostaje `'str'`, więc `_card_value` i tak odda `value_raw` i kontrakt z `read_xisf_header`
    stoi. Dzięki projekcji porównania liczbowe działają na XISF tak jak na FITS. Nieskończoności
    i NaN odrzucamy — nie są wartością do porównywania."""
    try:
        num = float(text)
    except (TypeError, ValueError):
        return None
    return num if math.isfinite(num) else None


@dataclass(frozen=True)
class XisfMeta:
    """Komplet zeznania + odcisków + MATERIAŁU ŁATY z jednego otwarcia pliku XISF (P6a).

    `xml_bytes` = nagłówek 1:1 (materiał łaty i backupu undo); `padding` = bajty między końcem XML
    a pierwszym blokiem danych, `reserved` = 4 B [12,16) — OBA kopiowane verbatim przy zapisie
    (D-X-1: wypełnienie jest zerowe w 330/330 plików, ale kopia nie kosztuje nic i nie zakłada
    niczego). `first_attachment` = MIN pozycji po WSZYSTKICH blokach `attachment:` (D-X-2) — sufit
    nagłówka; `image_span` = attachment PIERWSZEGO `<Image>` w kolejności dokumentu, czyli
    TOŻSAMOŚĆ klatki (`sha1_data`). To DWA różne fakty: sufit bierze minimum ze wszystkiego,
    tożsamość bierze pierwszy obraz."""
    header: dict
    cards: list
    header_hash: str
    xml_bytes: bytes
    padding: bytes
    reserved: bytes
    first_attachment: object          # int | None — brak bloku attachment (degenerat, D-X-13)
    image_span: object                # (start, size) | None — wejście sha1_data
    keyword_images: int               # ile <Image> NIESIE karty — >1 = cel niejednoznaczny (D-X-11)

    @property
    def padding_complete(self):
        """Czy bajty między nagłówkiem a pierwszym blokiem danych są KOMPLETNE — BRAMKA PISARZA.

        `False` znaczy, że plik przeczy sam sobie (deklarowany blok wchodzi w nagłówek albo pliku
        brakuje przed blokiem). Odczyt to przeżywa (zeznanie i tożsamość są całe), ale łata NIE
        MA PRAWA ruszyć: pisarz składa plik z `xml + padding + ogon`, więc niekompletne wypełnienie
        przesunęłoby bloki danych. Trzymamy tę arytmetykę TU, żeby pisarz nie liczył jej po raz
        drugi — pomyłka o 4 B przy `XISF_XML_OFFSET` nadpisuje pierwszy blok mastera (§0)."""
        if self.first_attachment is None:
            return False
        return len(self.padding) == self.first_attachment - XISF_XML_OFFSET - len(self.xml_bytes)


def read_xisf_meta_full(path):
    """Odczytaj nagłówek XISF (monolithic) jako `XisfMeta` — jedno przejście, wszystkie fakty.

    Karty (D-X-4/4a) powstają w TEJ SAMEJ pętli co dict zeznania, z tego samego filtra i tej samej
    wartości — lustro 1:1 nie jest tu obietnicą, tylko konstrukcją: rozjazd wymagałby dwóch pętli,
    a jest jedna. `value_type` ZAWSZE `'str'` (XISF trzyma wartości jako tekst), `value_num` to
    projekcja liczbowa (D-X-4); `comment` z atrybutu `comment` (D-X-5 — COMMENT/HISTORY mają
    `value=""`, treść siedzi w komentarzu; dict zeznania zostaje NIETKNIĘTY).

    `header_hash` = sha1 bajtów `[16, 16+hlen)`, BEZ wypełnienia (D-X-3) — odpowiednik
    `sha1(hdr.tostring())` z FITS.

    Read-only. Podnosi wyjątek przy złej sygnaturze / uciętym nagłówku / niepoprawnym XML — łapie
    to `scan_file` (miękkie lądowanie W1), nie użytkownik."""
    with open(path, "rb") as fh:
        signature = fh.read(len(_XISF_SIGNATURE))
        if signature != _XISF_SIGNATURE:
            raise ValueError(f"nie XISF monolithic (sygnatura {signature!r})")
        length_bytes = fh.read(_XISF_LENGTH_LEN)
        if len(length_bytes) < _XISF_LENGTH_LEN:
            raise ValueError("XISF: brak pola długości nagłówka")
        (header_len,) = struct.unpack("<I", length_bytes)
        reserved = fh.read(_XISF_RESERVED_LEN)
        if len(reserved) < _XISF_RESERVED_LEN:
            raise ValueError("XISF: brak pola reserved")
        xml_bytes = fh.read(header_len)
        if len(xml_bytes) < header_len:
            raise ValueError(f"XISF: nagłówek XML ucięty ({len(xml_bytes)}/{header_len} B)")

        root = ET.fromstring(xml_bytes)   # ParseError przy niepoprawnym XML → łapie scan_file
        header, cards = {}, []
        counts = {}
        image_span = None
        first_attachment = None
        for elem in root.iter():
            local = _local_name(elem.tag)
            loc = (elem.get("location") or "").split(":")
            if len(loc) == 3 and loc[0] == "attachment":
                pos = int(loc[1])
                # sufit nagłówka = MIN po WSZYSTKICH blokach (D-X-2); kolejność dokumentu pokrywa
                # się dziś z bajtową w 330/330 plików, ale to POMIAR, nie gwarancja formatu.
                first_attachment = pos if first_attachment is None else min(first_attachment, pos)
                if local == "Image" and image_span is None:
                    image_span = (pos, int(loc[2]))
            if local != "FITSKeyword":
                continue
            name = elem.get("name")
            if not name:                  # FITSKeyword bez nazwy — nic do zaadresowania, pomiń
                continue
            keyword = name.strip().upper()
            value_raw = _unquote_fits(elem.get("value", ""))
            idx = counts.get(keyword, 0)
            counts[keyword] = idx + 1
            cards.append(Card(keyword, idx, value_raw, _xisf_value_num(value_raw), "str",
                              elem.get("comment") or None))
            _put(header, keyword, value_raw)

        # Wypełnienie czytamy BEST-EFFORT i NIGDY nie wywracamy na nim odczytu: bajty LEŻĄCE ZA
        # nagłówkiem nie mogą unieważnić samego nagłówka. Plik z deklaracją bloku wchodzącą
        # w nagłówek albo ucięty przed blokiem ma nadal czytelne zeznanie i tożsamość — gdyby
        # czytnik tu rzucał, `scan_file` zdegradowałby go do W1 (`header=None`) i klatka straciłaby
        # kamerę/kind. Sprzeczność jest faktem o ZAPISIE i tam ma zatrzymać robotę: bramką jest
        # `padding_complete`, którą pisarz sprawdza przed łatą (D-X-2).
        padding = b""
        pad_len = (first_attachment - (XISF_XML_OFFSET + header_len)
                   if first_attachment is not None else 0)
        if pad_len > 0:
            padding = fh.read(pad_len)

    # Ile obrazów NIESIE karty (D-X-11) — osobne przejście, bo to pytanie o RODZICA keyworda,
    # a płaski `root.iter()` rodzica nie zna. Dziś 0 plików ma >1 (sonda #5 na 330 realnych), więc
    # to asercja EXPECT na przyszłość: przy dwóch obrazach z kartami „TELESCOP klatki" przestaje
    # mieć jedną odpowiedź i pisarz musi odmówić, zamiast wybrać za usera.
    keyword_images = sum(1 for e in root.iter() if _local_name(e.tag) == "Image"
                         and any(_local_name(k.tag) == "FITSKeyword" for k in e.iter()))

    return XisfMeta(header=header, cards=cards,
                    header_hash=hashlib.sha1(xml_bytes).hexdigest(),
                    xml_bytes=xml_bytes, padding=padding, reserved=reserved,
                    first_attachment=first_attachment, image_span=image_span,
                    keyword_images=keyword_images)


def build_xisf_header_region(meta, new_xml):
    """Bajty `[0, first_attachment)` po podmianie nagłówka XML — JEDYNE miejsce, gdzie liczy się
    arytmetykę offsetów przy zapisie XISF (§0: pomyłka o 4 B nadpisuje pierwszy blok mastera,
    a pisarz nie ma prawa przeliczać jej po raz drugi).

    Składa: sygnatura + NOWA długość + `reserved` verbatim + `new_xml` + wypełnienie. Region ma
    STAŁY ROZMIAR — offsety bloków danych są bezwzględne i zapisane w XML-u, więc dane się NIE
    RUSZAJĄ, a wypełnienie kurczy się/rośnie dokładnie o deltę długości nagłówka. Zmiana dzieje się
    na POCZĄTKU wypełnienia (tam, gdzie XML w nie wchodzi); ogon — ten stykający się z nieruchomym
    blokiem danych — zostaje verbatim (D-X-1). Skrócenie dokłada ZERA: bajtów, które nadpisał
    dłuższy nagłówek, nie da się wskrzesić, a wypełnienie z definicji nie niesie treści (zmierzone:
    zerowe w 330/330 plików).

    `ValueError` (wołający → `blocked`) gdy: brak bloku attachment (nie wiadomo, gdzie kończy się
    nagłówek), plik przeczy sam sobie (`padding_complete`), nagłówek nie mieści się w rezerwie
    (D-X-2). Trzeciej drogi nie ma — dane nie ustępują nagłówkowi."""
    if meta.first_attachment is None:
        raise ValueError("XISF: brak bloku attachment — nie wiadomo, gdzie kończy się nagłówek")
    if not meta.padding_complete:
        raise ValueError("XISF: wypełnienie nagłówka niekompletne — plik przeczy sam sobie")
    room = meta.first_attachment - XISF_XML_OFFSET
    if len(new_xml) > room:
        raise ValueError(
            f"XISF: nagłówek nie mieści się w rezerwie ({len(new_xml)} B > {room} B) — "
            f"attachmenty się nie ruszają")
    delta = len(new_xml) - len(meta.xml_bytes)
    padding = meta.padding[delta:] if delta > 0 else b"\x00" * -delta + meta.padding
    return _XISF_SIGNATURE + struct.pack("<I", len(new_xml)) + meta.reserved + new_xml + padding


def read_xisf_meta(path):
    """Odczytaj nagłówek XISF (monolithic) jako `(dict, span)`: dict zeznania — TEN SAM kontrakt
    co `read_fits_header` (klucze FITS wielkimi literami; COMMENT/HISTORY w listach), z jedną
    różnicą: wartości są STRINGAMI (XISF tak je trzyma; rzut na typ robią pola gorące — W3/§Etap 2).
    Wartości stringowe ODCUDZYSŁAWIANE z konwencji FITS (`_unquote_fits`, firsthand) — inaczej dict
    NIE byłby 1:1 z `read_fits_header` (astropy zwraca string bez apostrofów).

    `span` = `(start, size)` bajtów attachmentu PIERWSZEGO `<Image location="attachment:s:n">`
    w porządku dokumentu — dla masterów WBPP to obraz `integration` (właściwy stack; kolejne to
    rejection_low/high/slope_map). Wejście `sha1_of_span` → `sha1_data` XISF = sha1 bajtów
    attachmentu (brief §2; wzorzec `integ_hash` Custosa; postać kanoniczna przy kompresji = decyzja
    D-B na progu PF-4). None gdy brak obrazu-attachmentu (tożsamość nieobliczalna → degeneracja).

    Format (XISF 1.0 monolithic): sygnatura `XISF0100` (8 B) · uint32 LE długość nagłówka XML
    (4 B) · 4 B reserved · nagłówek XML (UTF-8). Czytamy WYŁĄCZNIE nagłówek (nie dotykamy bloków
    danych) → na Windowsie bez uchwytu blokującego (inwariant append-only, jak przy FITS).

    Wyłuskuje wszystkie `<FITSKeyword name= value=>` (oryginalne karty FITS, które PixInsight
    zachowuje 1:1; dopasowanie po nazwie lokalnej — odporne na namespace). `<Property>` (metadane
    natywne XISF) świadomie POMIJAMY w pierwszym przebiegu — pola gorące mieszkają w FITSKeyword.

    Podnosi wyjątek przy złej sygnaturze / uciętym nagłówku / niepoprawnym XML — skan nie zgaduje;
    łapie to `scan_file` (miękkie lądowanie W1), nie użytkownik.

    Od P6a to NAKŁADKA na `read_xisf_meta_full` (SPOT — jedna derywacja zeznania dla obu wejść);
    kontrakt `(dict, span)` bez zmian, `span` to nadal PIERWSZY `<Image>` w kolejności dokumentu.
    """
    meta = read_xisf_meta_full(path)
    return meta.header, meta.image_span


def read_xisf_header(path):
    """Odczytaj nagłówek XISF jako JSON-owalny dict (kontrakt sprzed PF-1 bez zmian; dziś
    cienka nakładka na `read_xisf_meta`)."""
    return read_xisf_meta(path)[0]


def read_header(path):
    """Dyspozytor czytnika nagłówka po rozszerzeniu (case-insensitive): `.xisf` → `read_xisf_header`,
    RAW (`.dng/.arw/.cr2`) → `exif.read_exif_header` (#2), pozostałe (FITS) → `read_fits_header`.
    Jeden punkt wejścia dla `scan_file` i pętli §Etap 4."""
    suffix = Path(path).suffix.lower()
    if suffix in XISF_SUFFIXES:
        return read_xisf_header(path)
    if suffix in exif.RAW_SUFFIXES:
        return exif.read_exif_header(path)
    return read_fits_header(path)


def _mtime_iso(st):
    """mtime ze `stat` jako ISO-8601 UTC — JEDNA derywacja dla `scan_file` (zapis do `location.mtime`)
    i bramy przyrostowej (`_already_scanned`, porównanie). MUSI być identyczna w obu miejscach: brama
    porównuje string znak-w-znak, więc każda rozbieżność formatu = wieczne PUDŁO (re-skan czyta
    wszystko). Sygnał zmiany pliku = WYŁĄCZNIE mtime (rozmiar NIE jest dyskryminatorem w astro)."""
    return datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat()


def scan_file(path):
    """Zeskanuj jeden plik (FITS lub XISF) → `ScanRecord` (odciski + stat + nagłówek + karty).
    Czysty odczyt.

    Miękkie lądowanie (W1): nagłówek nieczytelny/nierozpoznany NIE przerywa skanu — czytnik meta
    rzuca, my łapiemy i zwracamy `ScanRecord(header=None, error="Typ: opis")`; odciski sekcji
    (`sha1_data`/`header_hash`/`cards`) wtedy None, ale `file_sha1` i namiary są wypełnione
    (degeneracja tożsamości + frame/location powstaną; review nagłówka — wyżej).

    Hasze (brief §2): plik NIEskompresowany → `file_sha1` i `sha1_data` JEDNYM przebiegiem
    (`sha1_of_span`; pozycje sekcji z nagłówków przed odczytem treści); CompImageHDU →
    `file_sha1` strumieniem + `sha1_data` z dekompresji (`compressed_data_sha1`); XISF →
    `sha1_data` = sha1 bajtów attachmentu (ten sam jeden przebieg). Błąd I/O w fazie haszy
    propaguje (jak dawne `sha1_of`) — backstop to `scan_tree`, nie W1."""
    p = Path(path)
    st = p.stat()
    mtime = _mtime_iso(st)
    spath = str(p)
    header = None
    cards = header_hash = hdu_index = compressed = span = None
    try:
        suffix = p.suffix.lower()
        if suffix in exif.RAW_SUFFIXES:
            emeta = exif.read_exif_meta(spath)
            header, header_hash = emeta.header, emeta.header_hash
            cards = [Card(*row) for row in emeta.card_rows]   # opakuj krotki (unikamy cyklu importu)
            span = (0, st.st_size)        # D-R-1: tożsamość RAW = sha1 CAŁEGO pliku → sha1_data==file_sha1
        elif suffix in XISF_SUFFIXES:
            xmeta = read_xisf_meta_full(spath)
            header, cards, header_hash = xmeta.header, xmeta.cards, xmeta.header_hash
            span = xmeta.image_span       # `hdu_index`/`compressed` zostają None (D-X-7: obce formatowi)
        else:
            meta = read_fits_meta(spath)
            header, cards = meta.header, meta.cards
            header_hash, hdu_index, compressed = meta.header_hash, meta.hdu_index, meta.compressed
            span = (meta.datloc, meta.datspan)
        error = None
    except Exception as exc:              # W1: dowolny błąd czytnika → review, nie crash pętli
        error = f"{type(exc).__name__}: {exc}"
    if compressed:
        file_sha1 = sha1_of(spath)
        try:
            sha1_data = compressed_data_sha1(spath, hdu_index)
        except Exception:                 # zepsuty kafelek → tożsamość nieobliczalna (degeneracja:
            sha1_data = None              # sha1 pliku + flaga — składa ingest_record)
    else:
        file_sha1, sha1_data = sha1_of_span(spath, span)
    return ScanRecord(
        path=spath, size_bytes=st.st_size, mtime=mtime,
        header=header, error=error,
        sha1_data=sha1_data, file_sha1=file_sha1,
        header_hash=header_hash, hdu_index=hdu_index, compressed=compressed, cards=cards,
    )


@dataclass
class ScanSummary:
    """Zliczenia jednego przebiegu `scan_tree` — do firsthand-weryfikacji integralności."""
    files: int = 0
    frames_new: int = 0
    frames_existing: int = 0
    locations_new: int = 0
    locations_refreshed: int = 0   # znana ścieżka, fakty kopii odświeżone (mtime/hash/rozmiar — §2)
    headers_refreshed: int = 0     # zeznanie odświeżone po zmianie header_hash (writeback — §2)
    locations_rebound: int = 0     # podmiana treści pod znaną ścieżką → location przepięta (§2)
    headers: int = 0
    frame_review: int = 0
    camera_review: int = 0
    kind_unmapped: int = 0
    skipped: int = 0          # pliki POMINIĘTE bramą przyrostową (NIEczytane — bez sha1/nagłówka/DML)
    vanished: int = 0         # kopie znikłe MIĘDZY listowaniem a odczytem (backstop D-V-8; nie pass)
    dirs_excluded: int = 0    # podkatalogi z listy odcięte (drzewa robocze: _WBPP/_Review — nie schodzone)
    excluded_dirs: list = field(default_factory=list)   # ich ścieżki (diagnostyka — nie cichy licznik)
    cancelled: bool = False   # skan przerwany kooperatywnie (should_cancel) na granicy pliku


def _filetype(path):
    """Format pliku z rozszerzenia: `raw` (.dng/.arw/.cr2, #2) | `xisf` | `fits` (fit/fts też FITS).
    Vendor niesie już `INSTRUME` — spłaszczamy do `'raw'` (schemat 0002:16 przewidywał per-vendor,
    ale dyspozycja idzie po SUFIKSIE, nie po `filetype`; D-R-3/znal.7)."""
    suffix = Path(path).suffix.lower()
    if suffix in exif.RAW_SUFFIXES:
        return "raw"
    return "xisf" if suffix in XISF_SUFFIXES else "fits"


def path_gone(path):
    """DOWÓD NIEOBECNOŚCI pliku (P5/D-V-12) — TRÓJSTANOWY, bo „nie ma" i „nie wolno spojrzeć" to
    dwie różne odpowiedzi, a tylko pierwsza uprawnia do zdjęcia obecności (`present=0`):

      `True`  — system mówi NIE MA: `FileNotFoundError` (ENOENT) albo `NotADirectoryError`
                (ENOTDIR — komponent ścieżki przestał być katalogiem);
      `False` — plik jest;
      `None`  — NIE WIEM: każdy inny `OSError` (brak uprawnień, zerwany SMB, timeout, ELOOP).

    `os.path.exists` jest tu ZAKAZANY: zwraca `False` w OBU złych przypadkach, więc awaria sieci
    albo odebrane uprawnienia wyglądałyby jak skasowany plik. Wołający MUSI rozróżniać `is True`
    od falsy — `None` idzie do kubełka `undecided` (raport, ZERO zapisu).

    `os.stat` (nie `lstat`) — pytamy o plik, który byśmy PRZECZYTALI, więc podążamy za dowiązaniem;
    zerwane dowiązanie = treści nie ma. Hardlinki projekcji (`projection.py`) statują normalnie."""
    try:
        os.stat(path)
    except (FileNotFoundError, NotADirectoryError):
        return True
    except OSError:
        return None
    return False


def _already_scanned(con, volume, path, mtime):
    """Brama przyrostowa (§3.B / PLAN_skan §7.9): czy plik pod tą `(volume, path)` i `mtime` jest już
    w bazie I CZYTELNY — TANIA detekcja (`stat`) PRZED drogim `sha1_of` (pełny odczyt). Czysta funkcja
    `con→bool`, testowalna bez Qt.

    STAŁY literał SELECT + bind `?` (f-string wysadziłby bramkę AST §8.1 — `_first_sql_verb`=None dla
    nie-literału = offender poza repo.py/db.py). `UNIQUE(volume, path)` → ≤1 wiersz; `mtime`
    rozstrzyga „niezmieniony".

    GUARD MARKERA (#13): `unreadable_since IS NULL` — kopia OZNACZONA jako nieczytelna jest ZAWSZE
    re-czytana na każdym skanie (marker ją wyklucza z pominięcia), aż UDANY odczyt zgasi marker. Bez
    tego marker po transient awarii przy NIEZMIENIONYM mtime nigdy by nie zgasł: brama pomijałaby plik
    w nieskończoność, a kopia zostałaby wiecznie „nieczytelna" w stanie mimo faktycznego wyzdrowienia.

    GUARD ZMARTWYCHWSTANIA (P5/D-V-6): `present = 1` — kopia oznaczona jako zniknięta jest ZAWSZE
    re-czytana, gdy plik znów pojawi się na dysku. Bez tego powrót pliku o NIEZMIENIONYM `mtime`
    zostałby pominięty przez bramę i wiersz zostałby `present=0` na zawsze (pass zniknięć byłby
    drzwiami jednokierunkowymi). Koszt zerowy: bramę pytamy wyłącznie o pliki, które walk WIDZI
    na dysku, więc warunek dotyka tylko realnych powrotów. Obecność przywraca dopiero UDANY odczyt
    (`repo.refresh_location(present=1)`) — brama sama niczego nie zapisuje."""
    row = con.execute(
        "SELECT 1 FROM location WHERE volume=? AND path=? AND mtime=? "
        "AND unreadable_since IS NULL AND present = 1",
        (volume, path, mtime),
    ).fetchone()
    return row is not None


def _record_testimony_and_flags(con, rec, *, frame_id, sha1_data, readable, ident, kind,
                                now, summary, actor="scan"):
    """Zeznanie + flagi dla ŚWIEŻO powstałego frame'a (wspólne dla ścieżki nowej i przepiętej):
    czytelny → `record_header` (1:1, z cards) + ewentualne `flag_camera_review`/`flag_kind_unmapped`;
    nieczytelny → `flag_frame_review` (frame-SZKIELET bez headera)."""
    if not readable:                                   # W1: frame-szkielet bez headera → review
        repo.flag_frame_review(con, sha1=sha1_data, path=rec.path, reason=rec.error, now=now,
                               actor=actor)
        summary.frame_review += 1
        return
    repo.record_header(
        con, frame_id=frame_id, raw_json=json.dumps(rec.header, ensure_ascii=False),
        cards=rec.cards, now=now, actor=actor, **extract_header(rec.header))
    summary.headers += 1
    if ident is None:
        repo.flag_camera_review(
            con, frame_id=frame_id, reason="brak osi KAMERA (INSTRUME)", now=now, actor=actor)
        summary.camera_review += 1
    imagetyp = rec.header.get("IMAGETYP")
    if kind == "unknown" and imagetyp and str(imagetyp).strip():
        repo.flag_kind_unmapped(con, frame_id=frame_id, imagetyp=imagetyp, now=now, actor=actor)
        summary.kind_unmapped += 1


def _derive_kind(rec, *, readable, is_raw):
    """Rodzaj klatki + PROWIENIENCJA (#2, D-R-4). RAW nie ma IMAGETYP w EXIF → rodzaj z FOLDERU
    (`kind_source='path'`, precedens C1: ścieżka jako źródło faktu — wąski, jawny); FITS/XISF z
    IMAGETYP zeznania (`source='header'`); nieczytelny (W1) → `unknown`/None (brak zeznania)."""
    if not readable:
        return "unknown", None
    if is_raw:
        return kind_from_path(rec.path), "path"
    return normalize_kind(rec.header.get("IMAGETYP")), "header"


def ingest_record(con, rec, *, volume="?", drive_letter=None, tier=None, now, summary,
                  actor="scan"):
    """Wciągnij JEDEN `ScanRecord` przez jedną klingę (`repo`) — JĄDRO wspólne dla skanu drzewa
    (`scan_tree`) i importu z dawcy (rekord pochodzi z nagłówka pliku ALBO z cache'owanego
    źródła). Mutuje `summary`; zapis WYŁĄCZNIE przez `repo` (zero DML tutaj). `actor` idzie do
    KAŻDEGO eventu tej ścieżki (import z dawcy podaje `import:fitsmirror`, brief §4.2).

    TOŻSAMOŚĆ (brief §2): frame po `sha1_data` (odcisk sekcji danych); nieobliczalny →
    DEGENERACJA (sha1 całego pliku + `sha1_data_uncomputable=1`) — legalna WYŁĄCZNIE dla ścieżki
    NIEZNANEJ (R3-b1). Fakty kopii (file_sha1/header_hash/hdu_index/compressed/size_bytes) idą
    na location.

    ŚCIEŻKA NIEZNANA (brak wiersza `location(volume,path)`):
      - oś KAMERA (`camera_identity`→`upsert_camera`) i `normalize_kind` tylko dla CZYTELNEGO
        nagłówka; nieczytelny (W1) → `kind='unknown'`, `camera_id=None`;
      - `upsert_frame` + `add_location` (idempotentnie). NOWY frame → zeznanie/flagi
        (`_record_testimony_and_flags`); ISTNIEJĄCY sha1_data → tylko nowa `location`
        (multi-location); zeznanie z PIERWSZEGO wystąpienia (reguła N-lokacji, §2).

    ŚCIEŻKA ZNANA — kontrakt świeżości §2 (domyka dług „mtime nieaktualizowany"):
      - plik NIECZYTELNY, bajty NIEZMIENIONE → `refresh_location_unreadable` (mtime + MARKER
        `unreadable_since` + frame.review, ZERO nowych frame'ów; #13). Wołane BEZWARUNKOWO — cichy
        no-op idempotentnego re-skanu rozstrzyga repo (zwraca False, gdy powtórna awaria niczego nie
        zmienia); `summary.frame_review` rośnie TYLKO gdy repo zwróciło True;
      - PODMIANA TREŚCI (świeża tożsamość ≠ tożsamość frame'a lokacji — WBPP re-generuje master
        pod tą samą nazwą): `upsert_frame` (ew. degenerat) + `rebind_location` + świeże fakty
        kopii; stary frame ZOSTAJE (append-only) — BEZ żadnej lokacji, więc pass zniknięć (oparty
        na lokacjach) go NIE podchwyci; ślad niesie `location.rebound` (P5, `repo.rebind_location`);
      - ta sama tożsamość → `refresh_location`: fakty kopii + (przy zmianie `header_hash`)
        odświeżenie zeznania i pochodnych frame'a (last-read-wins). Udany odczyt GASI marker
        `unreadable_since` (kopia wyzdrowiała; #13), degeneracja go zakłada/trzyma.

    OBECNOŚĆ (P5/D-V-6): każda ścieżka docierająca tutaj została ODCZYTANA (`scan_file`) albo
    ZESTATOWANA (preflight importu odsiewa braki do `skipped`), więc obie gałęzie `refresh_location`
    podają `present=1` — to DOWÓD obecności, nie domysł. Kopia wracająca po zniknięciu wraca tą
    drogą (brama jej nie pomija, D-V-6) i dostaje `location.refreshed` z `{present:{0→1}}`.

    NIE łapie wyjątków — backstop bez tożsamości (sha1 nieznany → `frame.review`, sha1='?') należy
    do wołającego (`scan_tree` / import), bo to on wie, jak zidentyfikować rekord do review."""
    readable = rec.header is not None
    is_raw = _filetype(rec.path) == "raw"          # #2: FAKT formatu (→ raw_format, kind z folderu)
    ident = camera_identity(rec.header, raw_format=is_raw) if readable else None
    camera_id = None
    if ident is not None:
        camera_id, _ = repo.upsert_camera(
            con, model_canon=ident.model_canon, pixel_um=ident.pixel_um,
            is_mono=ident.is_mono, is_mono_source=ident.is_mono_source,
            raw_instrume=ident.raw_instrume, now=now, actor=actor)
    kind, kind_source = _derive_kind(rec, readable=readable, is_raw=is_raw)
    if rec.sha1_data is not None:
        sha1_data, uncomputable = rec.sha1_data, 0
    else:                                              # degeneracja: sha1 pliku + flaga
        sha1_data, uncomputable = rec.file_sha1, 1

    loc = con.execute(
        "SELECT id, frame_id, mtime, file_sha1, unreadable_since "
        "FROM location WHERE volume = ? AND path = ?",
        (volume, rec.path)).fetchone()

    if loc is None:                                    # ścieżka NIEZNANA — dotychczasowy tor
        frame_id, created = repo.upsert_frame(
            con, sha1_data=sha1_data, sha1_data_uncomputable=uncomputable,
            kind=kind, kind_source=kind_source, filetype=_filetype(rec.path),
            camera_id=camera_id, now=now, actor=actor)
        if created:
            summary.frames_new += 1
        else:
            summary.frames_existing += 1
        _, loc_created = repo.add_location(
            con, frame_id=frame_id, volume=volume, drive_letter=drive_letter,
            path=rec.path, tier=tier, mtime=rec.mtime,
            file_sha1=rec.file_sha1, header_hash=rec.header_hash, hdu_index=rec.hdu_index,
            compressed=rec.compressed, size_bytes=rec.size_bytes, now=now, actor=actor)
        if loc_created:
            summary.locations_new += 1
        if created:                                    # header 1:1 z frame → tylko dla nowego
            _record_testimony_and_flags(
                con, rec, frame_id=frame_id, sha1_data=sha1_data, readable=readable,
                ident=ident, kind=kind, now=now, summary=summary, actor=actor)
        return

    # ── ścieżka ZNANA: kontrakt świeżości §2 ──
    frame_row = con.execute(
        "SELECT sha1_data FROM frame WHERE id = ?", (loc["frame_id"],)).fetchone()

    if not readable and rec.file_sha1 == loc["file_sha1"]:
        # R3-b1 (#13): znana kopia nieczytelna, bajty bez zmian → refresh mtime + MARKER
        # `unreadable_since` (znacznik czytelności w STANIE) + review; ZERO nowych frame'ów
        # (degeneracja tożsamości legalna wyłącznie dla ścieżki nieznanej). Marker trzyma alarm i
        # wymusza re-odczyt przez bramę aż do wyzdrowienia; `refresh_location_unreadable` zwraca
        # False przy powtórnej awarii bez zmiany (QUIET) → wtedy licznik review milczy.
        summary.frames_existing += 1
        if repo.refresh_location_unreadable(
                con, location_id=loc["id"], sha1_data=frame_row["sha1_data"], path=rec.path,
                mtime=rec.mtime, reason=rec.error, now=now, actor=actor):
            summary.frame_review += 1
        return

    frame_id = loc["frame_id"]
    # Marker czytelności kopii (#13) dla OBU gałęzi refresh_location: udany odczyt (readable) gasi
    # marker (None); rekord nieczytelny wpadający tu przez DEGENERACJĘ (podmiana treści na
    # nieczytelną) trzyma/zakłada marker (istniejący timestamp albo `now`) — marker ma zostać, nie zgasnąć.
    unreadable_after = None if readable else (loc["unreadable_since"] or now)
    if sha1_data != frame_row["sha1_data"]:            # PODMIANA TREŚCI pod znaną ścieżką
        frame_id, created = repo.upsert_frame(
            con, sha1_data=sha1_data, sha1_data_uncomputable=uncomputable,
            kind=kind, kind_source=kind_source, filetype=_filetype(rec.path),
            camera_id=camera_id, now=now, actor=actor)
        if created:
            summary.frames_new += 1
        else:
            summary.frames_existing += 1
        repo.rebind_location(con, location_id=loc["id"], frame_after=frame_id, now=now,
                             actor=actor)
        summary.locations_rebound += 1
        if created:
            _record_testimony_and_flags(
                con, rec, frame_id=frame_id, sha1_data=sha1_data, readable=readable,
                ident=ident, kind=kind, now=now, summary=summary, actor=actor)
        # świeże fakty kopii BEZ odświeżania zeznania (zeznanie nowego frame'a właśnie nagrane,
        # a cudzemu — istniejącemu sha1_data — nie nadpisujemy: reguła N-lokacji)
        refreshed = repo.refresh_location(
            con, location_id=loc["id"], frame_id=frame_id, mtime=rec.mtime,
            file_sha1=rec.file_sha1, header_hash=rec.header_hash, hdu_index=rec.hdu_index,
            compressed=rec.compressed, size_bytes=rec.size_bytes, unreadable_since=unreadable_after,
            present=1, now=now, actor=actor)
        summary.locations_refreshed += refreshed["facts"]
        return

    # ta sama tożsamość pod znaną ścieżką → refresh faktów (+ zeznania przy zmianie header_hash)
    summary.frames_existing += 1
    refreshed = repo.refresh_location(
        con, location_id=loc["id"], frame_id=frame_id, mtime=rec.mtime,
        file_sha1=rec.file_sha1, header_hash=rec.header_hash, hdu_index=rec.hdu_index,
        compressed=rec.compressed, size_bytes=rec.size_bytes, unreadable_since=unreadable_after,
        present=1, now=now, actor=actor,
        raw_json=json.dumps(rec.header, ensure_ascii=False) if readable else None,
        cards=rec.cards, hot_fields=extract_header(rec.header) if readable else None,
        camera_id=camera_id, kind=kind)
    summary.locations_refreshed += refreshed["facts"]
    summary.headers_refreshed += refreshed["header"]


def canonize_root(root):
    """Kanonizacja ROOTA skanu — jawna SEKWENCJA (brief §0, R3-a1) zamiast `realpath`/`resolve`
    (te na zamapowanym `R:` rozwiązują do UNC — ŚWIĘTY zakaz w torze tożsamości ścieżek):

      1. `str(Path(root))` — separatory `/`→`\\`, zdjęcie trailing separatora;
      2. `os.path.abspath` — LEKSYKALNE ukotwiczenie (NIE rozwiązuje SMB/symlinków);
      3. **guard UNC (R3-a2):** root `\\\\host\\share` → odmowa „zamapuj literę dysku"
         (tożsamość `location.path` jest LITEROWA; UNC dublowałby lokacje przy tym samym
         `volume_serial` i brama by pudłowała);
      4. `GetLongPathNameW` — casing/długa forma Z DYSKU (zachowuje literę dysku — skill
         `windows-mapped-drive-path-identity`); zwrot 0 = root nie istnieje → **abort** (EXPECT);
      5. wielka litera dysku.

    Komponenty PONIŻEJ roota niesie `os.walk` (readdir — casing z dysku, jak u dawcy).
    Poza Windows: kroki 4–5 nieczynne (brak API i liter dysków) — zostaje 1–3."""
    s = os.path.abspath(str(Path(root)))
    if s.startswith("\\\\"):
        raise ValueError(
            f"root UNC ({s!r}) poza torem tożsamości — zamapuj literę dysku i skanuj przez nią")
    if sys.platform == "win32":
        buf = ctypes.create_unicode_buffer(32768)
        n = ctypes.windll.kernel32.GetLongPathNameW(s, buf, 32768)
        if n == 0:                        # EXPECT: root nie istnieje / niedostępny → abort
            raise FileNotFoundError(f"root skanu nie istnieje albo niedostępny: {s}")
        s = buf.value
        if len(s) >= 2 and s[1] == ":":
            s = s[0].upper() + s[1:]
    return s


@dataclass
class BackfillSummary:
    """Zliczenia jednego przebiegu `backfill_xisf_headers` — kotwica idempotencji jest w `remaining`."""
    rows: int = 0             # lokacje wybrane sterownikiem (kandydaci)
    read: int = 0             # realnie odczytane z dysku (scan_file nie rzucił)
    failed: int = 0           # odczyt/`stat` padł → ZERO zapisu dla tej lokacji
    remaining: int = 0        # kandydaci PO przebiegu (0 = komplet; >0 = pliki nie do przeczytania)
    failed_paths: list = field(default_factory=list)
    scan: ScanSummary = field(default_factory=ScanSummary)   # eventy/odświeżenia z `ingest_record`


def _xisf_backfill_rows(con):
    """Kandydaci backfillu (D-X-8): lokacje XISF BEZ `header_hash`, obecne. STAŁY literał SELECT —
    ten sam, którym mierzymy `remaining`, więc „pusto po przebiegu" znaczy dokładnie to samo, co
    „nie ma czego backfillować" (jedno pytanie, nie dwa)."""
    return con.execute(
        "SELECT l.id, l.volume, l.path FROM location l JOIN frame f ON f.id = l.frame_id "
        "WHERE f.filetype = 'xisf' AND l.header_hash IS NULL AND l.present = 1 ORDER BY l.id"
    ).fetchall()


def backfill_xisf_headers(con, *, now, progress=None):
    """STEROWNIK CELOWANY (P6/D-X-8): dociągnij `cards` + `header_hash` do lokacji XISF, które
    powstały PRZED P6a (skan zwracał dla XISF `None`). Zwraca `BackfillSummary`.

    DLACZEGO nie `scan_tree --force`: globalny re-skan czytałby 839 GB i nie miałby kotwicy
    „skończone". Sterownik pyta bazę o DOKŁADNIE te lokacje, których dotyczy brak
    (`filetype='xisf' AND header_hash IS NULL AND present=1`), i po przebiegu ten sam SELECT jest
    pusty — idempotencja za darmo (`remaining`). Ponowne wywołanie = no-op bez czytania dysku.

    JEDNA ŚCIEŻKA ZAPISU (SPOT): `scan_file` → `ingest_record` — ta sama, którą chodzi skan i import.
    `volume` bierzemy Z WIERSZA (pominięcie dałoby 331 NOWYCH lokacji pod `volume='?'`).
    `ORDER BY l.id` = determinizm dla 5 klatek o dwóch kopiach: obie lokacje są kandydatami, zeznanie
    zostaje po OSTATNIEJ przeczytanej (świadome, jednorazowe last-read-wins wbrew regule „zeznanie
    z pierwszego wystąpienia" — bajty attachmentu są identyczne, więc różni je najwyżej nagłówek).

    SKUTKI ŚWIADOME (D-X-8a/8b): `header_hash` NULL→wartość jest zmianą faktu kopii, więc
    `refresh_location` odświeża zeznanie i wstawia karty — event PARAMI, nie tylko dla klatek z GPS.
    Zmierzone na żywej `horreum_pf4.db` 2026-07-22: 330 `location.refreshed` + 330 `header.refreshed`
    + 1 `frame.review`, wszystkie z `actor='backfill:xisf'` (dziennik ma je odróżniać od skanu).
    Karty SITELAT/SITELONG stają się widoczne dla `resolver.resolve_observatory`, więc NASTĘPNY
    `resolve` przypisze XISF-om stanowisko — to jest zamierzone, nie efekt uboczny.

    Plik nieczytelny (`scan_file` rzuca) → `failed` + ścieżka do raportu, ZERO zapisu: backfill nie
    jest passem obecności ani skanem, więc nie stawia markerów i nie zdejmuje obecności — od tego
    są `scan_tree` i `presence`. Plik czytelny, ale bez parsowalnego nagłówka (XISF z `ParseError`)
    idzie normalną ścieżką `ingest_record` (marker `unreadable_since` — kopia FAKTYCZNIE nieczytelna)
    i zostaje w `remaining`."""
    rows = _xisf_backfill_rows(con)
    s = BackfillSummary(rows=len(rows))
    total = len(rows)
    for i, row in enumerate(rows, 1):
        path = row["path"]
        try:
            rec = scan_file(path)
        except Exception as exc:               # brak pliku / I/O — raport, nie zapis (patrz docstring)
            s.failed += 1
            s.failed_paths.append(f"{path}: {type(exc).__name__}: {exc}")
        else:
            s.read += 1
            ingest_record(con, rec, volume=row["volume"], now=now, summary=s.scan,
                          actor="backfill:xisf")
        if progress is not None:
            progress(i, total, path)
    s.remaining = len(_xisf_backfill_rows(con))
    return s


def scan_tree(con, root, *, volume="?", drive_letter=None, tier=None, now,
              progress=None, should_cancel=None):
    """Pętla PŁASKA: każdy plik nagłówkonośny w `root` oceniany RAZ i wciągany przez jedną klingę
    (`repo`). Jeden plik = jedno dotknięcie (§1.2). Zapis WYŁĄCZNIE przez `repo` (zero DML tutaj).

    Per plik: brama przyrostowa → `scan_file` (read-only) → `ingest_record` (jądro). Backstop W1:
    dowolny nieoczekiwany wyjątek per-plik NIE wywala całości — skan leci dalej. Rozstrzygnięcie
    zależy od tego, czy ścieżka jest ZNANA (#13): ZNANA → `refresh_location_unreadable` (marker
    `unreadable_since`, idempotentnie — powtórna awaria to cichy no-op, nie spam review); NIEZNANA →
    `flag_frame_review(sha1='?')` (backstop bez tożsamości — brak kotwicy UNIQUE, może się powtórzyć).
    `now` jawny (ISO-8601) — deterministyczne testy. Zwraca `ScanSummary`.

    BRAMA PRZYROSTOWA (§3.B) — aktywna ⟺ `volume != '?'`. Gdy znamy trwały serial woluminu,
    plik o znanym `(volume, path, mtime)` jest POMIJANY bez `sha1_of` (drogi pełny odczyt) i bez DML
    (`summary.skipped += 1`). `volume='?'` (serial nieustalony) → brama OFF → pełny skan (zero
    fałszywych pominięć — `volume` to nie tożsamość frame'a, §7.5).

    HOOKI GUI (Qt-WOLNE; rdzeń nic nie wie o Qt):
      - `should_cancel: ()->bool` — sprawdzane na GÓRZE pętli, PRZED plikiem; `True` ⇒ `break` +
        `cancelled=True`. Anulowanie na GRANICY PLIKU: bieżący plik albo cały wciągnięty, albo
        nietknięty (bezpieczeństwo z `break` przed `scan_file`, NIE z commitu per-call).
      - `progress: (done, total, path, summary)->None` — wołane po KAŻDYM pliku (też pominiętym),
        `total=len(paths)` (lista zmaterializowana → darmowe). Snapshot/emisja sygnału Qt to robota
        callbacku GUI; rdzeń woła synchronicznie.
    """
    summary = ScanSummary()
    excluded = []
    root = canonize_root(root)                             # forma literowa + casing z dysku; UNC → odmowa (§0)
    paths = iter_headers(root, excluded_out=excluded)      # drzewa robocze odcięte (EXCLUDED_DIR_NAMES: _WBPP/_Review)
    summary.excluded_dirs = excluded
    summary.dirs_excluded = len(excluded)
    total = len(paths)
    gate_on = volume != "?"
    for path in paths:
        if should_cancel is not None and should_cancel():
            summary.cancelled = True
            break
        summary.files += 1
        spath = str(path)
        try:
            skip = gate_on and _already_scanned(con, volume, spath, _mtime_iso(path.stat()))
            if skip:
                summary.skipped += 1
            else:
                rec = scan_file(spath)
                ingest_record(con, rec, volume=volume, drive_letter=drive_letter, tier=tier,
                              now=now, summary=summary)
        except Exception as exc:                           # backstop W1: pojedynczy plik nie wywala skanu
            # Błąd I/O w scan_file (hasze są POZA try W1 — otwarcie/odczyt pliku propaguje) na ZNANEJ
            # ścieżce: oznacz marker `unreadable_since` przez klingę (#13) zamiast flagować sha1='?'
            # co skan. Bez tego marker znosi bramę → plik, który przestał się OTWIERAĆ, generowałby
            # +1 event/skan w nieskończoność. `mtime` bierzemy Z BAZY (bez zmiany) → powtórka to cichy
            # no-op (QUIET). Ścieżka NIEZNANA (brak location) → backstop bez tożsamości: sha1='?'.
            #
            # ROZGAŁĘZIENIE PO DOWODZIE (P5/D-V-8): plik mógł ZNIKNĄĆ między listowaniem a odczytem
            # (walk go widział, `stat`/otwarcie już nie). Marker znaczy „kopia JEST nieczytelna,
            # przeczytaj ją ponownie" — dla nieistniejącego pliku to kłamstwo bez wyjścia, a przy
            # `present=0` byłoby hybrydą zakazaną przez inwariant D-V-5. Rozstrzyga `_gone` (lstat +
            # errno), nie domysł; zniknięcie idzie do `mark_location_vanished` (ta sama klinga).
            reason = f"{type(exc).__name__}: {exc}"
            row = con.execute(
                "SELECT l.id, l.mtime, f.sha1_data FROM location l JOIN frame f ON f.id = l.frame_id "
                "WHERE l.volume = ? AND l.path = ?",
                (volume, spath)).fetchone()
            if row is not None and path_gone(spath) is True:
                if repo.mark_location_vanished(
                        con, location_id=row["id"], expected_path=spath, root=root, run_id=None,
                        now=now, actor="scan"):
                    summary.vanished += 1
            elif row is not None:
                if repo.refresh_location_unreadable(
                        con, location_id=row["id"], sha1_data=row["sha1_data"], path=spath,
                        mtime=row["mtime"], reason=reason, now=now):
                    summary.frame_review += 1
            else:
                repo.flag_frame_review(con, sha1="?", path=spath, reason=reason, now=now)
                summary.frame_review += 1
        if progress is not None:
            progress(summary.files, total, spath, summary)
    return summary
