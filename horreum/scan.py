"""Skan drzewa FITS + XISF — primitivy read-only + pętla płaska skanu (PLAN §4; §Etap 1/§Etap 4).

Per plik produkuje TOŻSAMOŚĆ + ZEZNANIE nagłówka, niczego nie zapisując:
  - odciski (PF-1 przejścia fitsmirror, brief §2 — port z dawcy `fits_io.py`):
      * `sha1_data` = sha1 sekcji DANYCH wybranego HDU (FITS) / bajtów attachmentu (XISF) —
        przyszła tożsamość frame'a (PF-2): przeżywa edycję nagłówka/rename/move/writeback,
      * `file_sha1` = sha1 całego pliku (fakt KOPII; do PF-2 pod starą nazwą pola `sha1` — R3-d1);
        dla pliku nieskompresowanego OBA hasze liczone JEDNYM przebiegiem (`sha1_of_span` —
        pozycje sekcji z nagłówków przed odczytem treści),
      * `header_hash` = sha1 tekstu nagłówka (kontrola writeback/undo; NULL dla XISF),
      * `cards` = pełne lustro nagłówka FITS (EAV: keyword/idx/value_raw/value_num/value_type/comment).
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
`scan_file` (zwraca `ScanRecord(header=None, error=...)`, tożsamość `sha1` ZACHOWANA), nie pętla
ani użytkownik. Nierozstrzygalność trafia do `event(*.review)` w warstwie upsertu (§Etap 4).
"""
import hashlib
import json
import os
import struct
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from astropy.io import fits

from . import repo
from .hashing import sha1_of, sha1_of_span
from .resolve.cameras import camera_identity
from .resolve.frames import normalize_kind
from .resolve.headers import extract_header

# Rozszerzenia nagłówkonośne pierwszego przebiegu (PLAN §1.1: jeden mechanizm, format = opakowanie).
# DSLR-raw (.ARW/.DNG, czytnik EXIF) to DRUGI przebieg / osobny moduł — NIE tu (PLAN §1.5).
FITS_SUFFIXES = (".fits", ".fit", ".fts")
XISF_SUFFIXES = (".xisf",)
HEADER_SUFFIXES = FITS_SUFFIXES + XISF_SUFFIXES

# Słowa-klucze nagłówkowe powtarzalne (komentarze/historia/puste) — akumulujemy w listę, żeby
# zeznanie było 1:1 (nie gubimy powtórzeń przez kolizję klucza w dict). Wspólne FITS↔XISF.
_MULTI_KEYWORDS = ("COMMENT", "HISTORY", "")

_XISF_SIGNATURE = b"XISF0100"        # monolithic XISF 1.0; po nim uint32 LE = długość nagłówka XML

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
    tożsamość (`sha1`) i namiary (`path`/`size`/`mtime`) są, lecz nagłówka/odcisków sekcji brak →
    review wyżej.

    Odciski przejścia (PF-1, brief §2) — do PF-2 WSPÓŁISTNIEJĄ ze starym polem `sha1` (R3-d1:
    `sha1` = sha1 całego pliku, dziś tożsamość frame'a w schemacie v1; znika razem ze schematem):
      - `sha1_data`: sha1 sekcji DANYCH HDU (FITS) / bajtów attachmentu (XISF); None = nieobliczalne
        (brak sekcji danych / zepsuty kafelek / W1) → degeneracja tożsamości, flagowana w PF-2;
      - `file_sha1`: sha1 całego pliku (fakt KOPII; wartość identyczna ze starym `sha1`);
      - `header_hash`/`hdu_index`/`compressed`: fakty kopii FITS (kontrola writeback/undo);
        None dla XISF (R2#14) i przy W1;
      - `cards`: pełne lustro nagłówka FITS (lista `Card`); None dla XISF (dojdzie w PF-4) i przy W1.
    """
    path: str                         # ścieżka bezwzględna (str — spójnie z sha1_of/repo)
    sha1: str                         # tożsamość frame'a schematu v1 (== file_sha1; do PF-2)
    size_bytes: int
    mtime: str                        # ISO-8601 UTC (klucz przyszłego cache sha1, §7.9)
    header: dict = field(default_factory=dict)   # pełny nagłówek, JSON-owalny; None gdy error
    error: object = None              # None gdy OK; tekst "Typ: opis" gdy nagłówek nieczytelny (W1)
    sha1_data: object = None          # przyszła tożsamość frame'a (PF-2); None = nieobliczalne
    file_sha1: object = None          # sha1 całego pliku (fakt kopii)
    header_hash: object = None        # sha1 tekstu nagłówka; None dla XISF/W1
    hdu_index: object = None          # HDU naukowe; None dla XISF/W1
    compressed: object = None         # 0/1 (CompImageHDU); None dla XISF/W1
    cards: object = None              # list[Card] — lustro nagłówka; None dla XISF/W1


def _iter_suffixes(root, suffixes, excluded_out=None):
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
    „POSORTOWANE" (jak dawne `rglob`+`sorted`)."""
    root = Path(root)
    out = []
    for dirpath, dirnames, filenames in os.walk(root):     # followlinks=False (domyślnie) — bez symlinków
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


def iter_headers(root, excluded_out=None):
    """Posortowane ścieżki WSZYSTKICH plików nagłówkonośnych pierwszego przebiegu (FITS + XISF,
    case-insensitive) w drzewie `root`. Wejście pętli płaskiej skanu (§Etap 4): jeden mechanizm,
    format = opakowanie (PLAN §1.1). Podkatalogi z `EXCLUDED_DIR_NAMES` odcięte (patrz
    `_iter_suffixes`); `excluded_out` zbiera ich ścieżki do telemetrii skanu."""
    return _iter_suffixes(root, HEADER_SUFFIXES, excluded_out=excluded_out)


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
    """
    with open(path, "rb") as fh:
        signature = fh.read(8)
        if signature != _XISF_SIGNATURE:
            raise ValueError(f"nie XISF monolithic (sygnatura {signature!r})")
        length_bytes = fh.read(4)
        if len(length_bytes) < 4:
            raise ValueError("XISF: brak pola długości nagłówka")
        (header_len,) = struct.unpack("<I", length_bytes)
        fh.read(4)                        # 4 B reserved (wg specyfikacji zerowe) — pomijamy
        xml_bytes = fh.read(header_len)
    if len(xml_bytes) < header_len:
        raise ValueError(f"XISF: nagłówek XML ucięty ({len(xml_bytes)}/{header_len} B)")
    root = ET.fromstring(xml_bytes)       # ParseError przy niepoprawnym XML → łapie scan_file
    out = {}
    span = None
    for elem in root.iter():
        local = _local_name(elem.tag)
        if local == "Image" and span is None:
            loc = (elem.get("location") or "").split(":")
            if len(loc) == 3 and loc[0] == "attachment":
                span = (int(loc[1]), int(loc[2]))
        if local != "FITSKeyword":
            continue
        name = elem.get("name")
        if not name:                      # FITSKeyword bez nazwy — nic do zaadresowania, pomiń
            continue
        _put(out, name.strip().upper(), _unquote_fits(elem.get("value", "")))
    return out, span


def read_xisf_header(path):
    """Odczytaj nagłówek XISF jako JSON-owalny dict (kontrakt sprzed PF-1 bez zmian; dziś
    cienka nakładka na `read_xisf_meta`)."""
    return read_xisf_meta(path)[0]


def read_header(path):
    """Dyspozytor czytnika nagłówka po rozszerzeniu (case-insensitive): `.xisf` → `read_xisf_header`,
    pozostałe (FITS) → `read_fits_header`. Jeden punkt wejścia dla `scan_file` i pętli §Etap 4."""
    if Path(path).suffix.lower() in XISF_SUFFIXES:
        return read_xisf_header(path)
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
    (`sha1_data`/`header_hash`/`cards`) wtedy None, ale tożsamość (`sha1` = sha1 całego pliku)
    i namiary są wypełnione (frame i location powstaną; review nagłówka — wyżej).

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
        if p.suffix.lower() in XISF_SUFFIXES:
            header, span = read_xisf_meta(spath)
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
            sha1_data = None              # sha1 pliku + flaga — flagowanie należy do PF-2)
    else:
        file_sha1, sha1_data = sha1_of_span(spath, span)
    return ScanRecord(
        path=spath, sha1=file_sha1, size_bytes=st.st_size, mtime=mtime,
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
    headers: int = 0
    frame_review: int = 0
    camera_review: int = 0
    kind_unmapped: int = 0
    skipped: int = 0          # pliki POMINIĘTE bramą przyrostową (NIEczytane — bez sha1/nagłówka/DML)
    dirs_excluded: int = 0    # podkatalogi z listy odcięte (drzewa robocze: _WBPP/_Review — nie schodzone)
    excluded_dirs: list = field(default_factory=list)   # ich ścieżki (diagnostyka — nie cichy licznik)
    cancelled: bool = False   # skan przerwany kooperatywnie (should_cancel) na granicy pliku


def _filetype(path):
    """Format pliku z rozszerzenia: `xisf` | `fits` (fit/fts też FITS). DSLR-raw = drugi przebieg."""
    return "xisf" if Path(path).suffix.lower() in XISF_SUFFIXES else "fits"


def _already_scanned(con, volume, path, mtime):
    """Brama przyrostowa (§3.B / PLAN_skan §7.9): czy plik pod tą `(volume, path)` i `mtime` jest już
    w bazie — TANIA detekcja (`stat`) PRZED drogim `sha1_of` (pełny odczyt). Czysta funkcja
    `con→bool`, testowalna bez Qt.

    STAŁY literał SELECT + bind `?` (f-string wysadziłby bramkę AST §8.1 — `_first_sql_verb`=None dla
    nie-literału = offender poza repo.py/db.py). `UNIQUE(volume, path)` → ≤1 wiersz; `mtime`
    rozstrzyga „niezmieniony". FORWARD-GUARD: gdy dojdzie pass zniknięć (`present`), dołożyć tu
    `AND present=1` lub resetować `present=1` na trafieniu — inaczej „zmartwychwstały" plik
    (present=0, ten sam mtime) zostałby pominięty. Dziś `present` zawsze 1 — uśpione.

    FORWARD-GUARD (prune wykluczeń): gdy dojdzie pass zniknięć, WYKLUCZENIE katalogu (np. `_WBPP`) to
    NIE to samo co zniknięcie pliku — plik istnieje, jest tylko poza zasięgiem skanu. Pass `present`
    MUSI liczyć `present=0` wyłącznie z faktycznie SKANOWANEGO poddrzewa (nie z tego, co prune odciął),
    inaczej przeniesienie danych pod wykluczony katalog fałszywie oznaczyłoby je jako znikłe (sieroty)."""
    row = con.execute(
        "SELECT 1 FROM location WHERE volume=? AND path=? AND mtime=?",
        (volume, path, mtime),
    ).fetchone()
    return row is not None


def ingest_record(con, rec, *, volume="?", drive_letter=None, tier=None, now, summary):
    """Wciągnij JEDEN `ScanRecord` przez jedną klingę (`repo`) — JĄDRO wspólne dla skanu drzewa
    (`scan_tree`) i przyszłego replayu/import-legacy (rekord pochodzi z nagłówka pliku ALBO z
    cache'owanego źródła). Mutuje `summary`; zapis WYŁĄCZNIE przez `repo` (zero DML tutaj).

    INWARIANT „baza zna wszystkie pliki" (D1): każdy rekord o znanym `sha1` daje frame + location,
    także gdy nagłówek nieczytelny (W1) → wtedy frame-SZKIELET (`kind='unknown'`, `camera_id=NULL`,
    bez `header`) + `flag_frame_review`. Spójne z `camera_review` (brak osi → frame jednak powstaje);
    znika dawne „W1 = brak frame'a". Re-skan idempotentny: sha1 UNIQUE jest kotwicą — istniejący
    szkielet NIE duplikuje `frame.review` (gating na `created`). [Backstop bez sha1 — `scan_tree`.]

      - oś KAMERA (`camera_identity`→`upsert_camera`; brak osi → `camera_id=None`) i `normalize_kind`
        tylko dla CZYTELNEGO nagłówka; nieczytelny (W1) → `kind='unknown'`, `camera_id=None`;
      - `upsert_frame` + `add_location` (zawsze, idempotentnie). NOWY frame: czytelny →
        `record_header` (1:1) + ewentualne `flag_camera_review` (brak osi) / `flag_kind_unmapped`
        (IMAGETYP niezmapowane); nieczytelny → `flag_frame_review` (szkielet, bez headera).
        ISTNIEJĄCY sha1 → tylko nowa `location` (multi-location), bez headera/flag (szkielet też
        nie „awansuje" przy późniejszym udanym odczycie — jak header 1:1 nie re-rejestruje się).

    NIE łapie wyjątków — backstop bez tożsamości (sha1 nieznany → `frame.review`, sha1='?') należy
    do wołającego (`scan_tree` / replay), bo to on wie, jak zidentyfikować rekord do review."""
    readable = rec.header is not None
    ident = camera_identity(rec.header) if readable else None
    camera_id = None
    if ident is not None:
        camera_id, _ = repo.upsert_camera(
            con, model_canon=ident.model_canon, pixel_um=ident.pixel_um,
            is_mono=ident.is_mono, is_mono_source=ident.is_mono_source,
            raw_instrume=ident.raw_instrume, now=now)

    kind = normalize_kind(rec.header.get("IMAGETYP")) if readable else "unknown"
    frame_id, created = repo.upsert_frame(
        con, sha1=rec.sha1, kind=kind, filetype=_filetype(rec.path),
        size_bytes=rec.size_bytes, camera_id=camera_id, now=now)
    if created:
        summary.frames_new += 1
    else:
        summary.frames_existing += 1

    _, loc_created = repo.add_location(
        con, frame_id=frame_id, volume=volume, drive_letter=drive_letter,
        path=rec.path, tier=tier, mtime=rec.mtime, now=now)
    if loc_created:
        summary.locations_new += 1

    if not created:                                    # header 1:1 z frame → tylko dla nowego
        return                                         # istniejący sha1 = dopisana sama location

    if not readable:                                   # W1: frame-szkielet bez headera → review
        repo.flag_frame_review(con, sha1=rec.sha1, path=rec.path, reason=rec.error, now=now)
        summary.frame_review += 1
        return

    repo.record_header(
        con, frame_id=frame_id, raw_json=json.dumps(rec.header, ensure_ascii=False),
        now=now, **extract_header(rec.header))
    summary.headers += 1
    if ident is None:
        repo.flag_camera_review(
            con, frame_id=frame_id, reason="brak osi KAMERA (INSTRUME/XPIXSZ)", now=now)
        summary.camera_review += 1
    imagetyp = rec.header.get("IMAGETYP")
    if kind == "unknown" and imagetyp and str(imagetyp).strip():
        repo.flag_kind_unmapped(con, frame_id=frame_id, imagetyp=imagetyp, now=now)
        summary.kind_unmapped += 1


def scan_tree(con, root, *, volume="?", drive_letter=None, tier=None, now,
              progress=None, should_cancel=None):
    """Pętla PŁASKA: każdy plik nagłówkonośny w `root` oceniany RAZ i wciągany przez jedną klingę
    (`repo`). Jeden plik = jedno dotknięcie (§1.2). Zapis WYŁĄCZNIE przez `repo` (zero DML tutaj).

    Per plik: brama przyrostowa → `scan_file` (read-only) → `ingest_record` (jądro). Backstop W1:
    dowolny nieoczekiwany wyjątek per-plik → `frame.review`, skan leci dalej (pojedynczy plik nie
    wywala całości). `now` jawny (ISO-8601) — deterministyczne testy. Zwraca `ScanSummary`.

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
            repo.flag_frame_review(
                con, sha1="?", path=spath, reason=f"{type(exc).__name__}: {exc}", now=now)
            summary.frame_review += 1
        if progress is not None:
            progress(summary.files, total, spath, summary)
    return summary
