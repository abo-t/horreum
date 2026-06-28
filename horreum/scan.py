"""Skan drzewa FITS + XISF — primitivy READ-ONLY fazy skanu (PLAN §4 krok 1; §Etap 1).

Per plik produkuje TOŻSAMOŚĆ + ZEZNANIE nagłówka, niczego nie zapisując:
  - `sha1_of` (binarnie 'rb') = tożsamość frame'a (przeżywa rename/move),
  - `read_header` (dyspozytor) = pełny nagłówek jako JSON-owalny dict:
      * FITS (.fits/.fit/.fts) → astropy, read-only,
      * XISF (.xisf) → lekki czytnik stdlib (`struct` + `xml.etree`), bez nowej zależności.
    To przyszłe `header.raw_json` + materiał dla pól gorących (§3.3/§3.5) — wyłuskanie należy do
    warstwy upsertu (krok §4.2). UWAGA W3: XISF zwraca wartości jako STRINGI; rzut na typ robią
    dopiero pola gorące (§Etap 2), nie ten moduł.

Ten moduł NIE dotyka bazy (żadnego DML — meta-tripwir AST to potwierdza) i NIE zapisuje na dysk
usera (inwariant append-only, PLAN §6): pliki otwierane WYŁĄCZNIE do odczytu. FITS przez astropy
`memmap=False` i bez sięgania po `.data`; XISF czyta tylko nagłówek (sygnatura + XML, bez bloków
danych) — więc na Windowsie nie zostaje uchwyt blokujący plik. `astropy` jest PIERWSZĄ zależnością
runtime Horreum (dochodzi z czytnikiem FITS); XISF korzysta wyłącznie ze stdlib.

Miękkie lądowanie (W1): `read_*` MOGĄ rzucać dla pliku nieczytelnego/nierozpoznanego — łapie to
`scan_file` (zwraca `ScanRecord(header=None, error=...)`, tożsamość `sha1` ZACHOWANA), nie pętla
ani użytkownik. Nierozstrzygalność trafia do `event(*.review)` w warstwie upsertu (§Etap 4).
"""
import struct
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from astropy.io import fits

from .hashing import sha1_of

# Rozszerzenia nagłówkonośne pierwszego przebiegu (PLAN §1.1: jeden mechanizm, format = opakowanie).
# DSLR-raw (.ARW/.DNG, czytnik EXIF) to DRUGI przebieg / osobny moduł — NIE tu (PLAN §1.5).
FITS_SUFFIXES = (".fits", ".fit", ".fts")
XISF_SUFFIXES = (".xisf",)
HEADER_SUFFIXES = FITS_SUFFIXES + XISF_SUFFIXES

# Słowa-klucze nagłówkowe powtarzalne (komentarze/historia/puste) — akumulujemy w listę, żeby
# zeznanie było 1:1 (nie gubimy powtórzeń przez kolizję klucza w dict). Wspólne FITS↔XISF.
_MULTI_KEYWORDS = ("COMMENT", "HISTORY", "")

_XISF_SIGNATURE = b"XISF0100"        # monolithic XISF 1.0; po nim uint32 LE = długość nagłówka XML


@dataclass(frozen=True)
class ScanRecord:
    """Wynik skanu jednego pliku (read-only). Materiał wejściowy dla upsertu frame/location/header
    (krok §4.2) — sam w sobie nie jest zapisem domenowym.

    `header is None` + `error` ustawione = plik nieczytelny/nierozpoznany (miękkie lądowanie W1):
    tożsamość (`sha1`) i namiary (`path`/`size`/`mtime`) są, lecz nagłówka brak → review wyżej.
    """
    path: str                         # ścieżka bezwzględna (str — spójnie z sha1_of/repo)
    sha1: str                         # tożsamość frame'a
    size_bytes: int
    mtime: str                        # ISO-8601 UTC (klucz przyszłego cache sha1, §7.9)
    header: dict = field(default_factory=dict)   # pełny nagłówek, JSON-owalny; None gdy error
    error: object = None              # None gdy OK; tekst "Typ: opis" gdy nagłówek nieczytelny (W1)


def _iter_suffixes(root, suffixes):
    """Przejdź drzewo `root` i wydaj POSORTOWANE ścieżki plików o danych rozszerzeniach
    (case-insensitive). Zwraca `Path`; pomija katalogi i inne rozszerzenia. Czysty odczyt katalogu."""
    root = Path(root)
    return sorted(
        p for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() in suffixes
    )


def iter_fits(root):
    """Posortowane ścieżki plików FITS (.fits/.fit/.fts, case-insensitive) w drzewie `root`.
    Prymityw FITS-only; pełny skan pierwszego przebiegu używa `iter_headers` (FITS + XISF)."""
    return _iter_suffixes(root, FITS_SUFFIXES)


def iter_headers(root):
    """Posortowane ścieżki WSZYSTKICH plików nagłówkonośnych pierwszego przebiegu (FITS + XISF,
    case-insensitive) w drzewie `root`. Wejście pętli płaskiej skanu (§Etap 4): jeden mechanizm,
    format = opakowanie (PLAN §1.1)."""
    return _iter_suffixes(root, HEADER_SUFFIXES)


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


def _select_header(hdul):
    """Wybierz nagłówek niosący metadane akwizycji. Zwykle PrimaryHDU (ext 0); dla
    skompresowanych masterów (CompImageHDU) primary bywa pusty (NAXIS=0) — wtedy pierwsze
    HDU z obrazem. Czytamy tylko nagłówki (NAXIS), nie ładując pikseli."""
    for hdu in hdul:
        if hdu.header.get("NAXIS", 0):
            return hdu.header
    return hdul[0].header             # awaryjnie: nagłówek primary, choćby bez danych


def _header_to_dict(hdr):
    """Nagłówek astropy → JSON-owalny dict (zeznanie 1:1). Powtarzalne COMMENT/HISTORY/puste
    akumulowane w listę, by nie zgubić wierszy przez kolizję klucza."""
    out = {}
    for card in hdr.cards:
        kw = card.keyword
        value = str(card.value) if kw in _MULTI_KEYWORDS else _jsonable(card.value)
        _put(out, kw, value)
    return out


def read_fits_header(path):
    """Odczytaj nagłówek FITS jako JSON-owalny dict. Read-only, bez ładowania pikseli, bez
    pozostawiania uchwytu (Windows). Podnosi wyjątek dla pliku, który nie jest FITS — faza
    skanu nie zgaduje (nierozstrzygalność trafia do `event(*.review)` w warstwie upsertu)."""
    with fits.open(path, mode="readonly", memmap=False) as hdul:
        return _header_to_dict(_select_header(hdul))


def _local_name(tag):
    """Lokalna nazwa znacznika XML bez przestrzeni nazw (`{ns}FITSKeyword` → `FITSKeyword`).
    PixInsight osadza nagłówek w `xmlns='http://www.pixinsight.com/xisf'`; dopasowanie po nazwie
    lokalnej jest odporne na obecność/wariant namespace (xml.etree przykleja `{ns}` do tagu)."""
    return tag.rsplit("}", 1)[-1]


def read_xisf_header(path):
    """Odczytaj nagłówek XISF (monolithic) jako JSON-owalny dict — TEN SAM kontrakt co
    `read_fits_header` (klucze FITS wielkimi literami; COMMENT/HISTORY w listach), z jedną
    różnicą: wartości są STRINGAMI (XISF tak je trzyma; rzut na typ robią pola gorące — W3/§Etap 2).

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
    for elem in root.iter():
        if _local_name(elem.tag) != "FITSKeyword":
            continue
        name = elem.get("name")
        if not name:                      # FITSKeyword bez nazwy — nic do zaadresowania, pomiń
            continue
        _put(out, name.strip().upper(), elem.get("value", ""))
    return out


def read_header(path):
    """Dyspozytor czytnika nagłówka po rozszerzeniu (case-insensitive): `.xisf` → `read_xisf_header`,
    pozostałe (FITS) → `read_fits_header`. Jeden punkt wejścia dla `scan_file` i pętli §Etap 4."""
    if Path(path).suffix.lower() in XISF_SUFFIXES:
        return read_xisf_header(path)
    return read_fits_header(path)


def scan_file(path):
    """Zeskanuj jeden plik (FITS lub XISF) → `ScanRecord` (sha1 + stat + nagłówek). Czysty odczyt.

    Miękkie lądowanie (W1): nagłówek nieczytelny/nierozpoznany NIE przerywa skanu — `read_header`
    rzuca, my łapiemy i zwracamy `ScanRecord(header=None, error="Typ: opis")`. Tożsamość (`sha1`)
    i namiary pliku są wypełnione mimo to (frame i location powstaną; review nagłówka — wyżej).
    """
    p = Path(path)
    st = p.stat()
    mtime = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat()
    sha1 = sha1_of(str(p))
    try:
        header = read_header(str(p))
        error = None
    except Exception as exc:              # W1: dowolny błąd czytnika → review, nie crash pętli
        header = None
        error = f"{type(exc).__name__}: {exc}"
    return ScanRecord(
        path=str(p), sha1=sha1, size_bytes=st.st_size, mtime=mtime,
        header=header, error=error,
    )
