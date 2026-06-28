"""Skan drzewa FITS — primitivy READ-ONLY fazy skanu (PLAN §4, krok 1).

Per plik produkuje TOŻSAMOŚĆ + ZEZNANIE nagłówka, niczego nie zapisując:
  - `sha1_of` (binarnie 'rb') = tożsamość frame'a (przeżywa rename/move),
  - `read_fits_header` (astropy, read-only) = pełny nagłówek FITS jako JSON-owalny dict
    (przyszłe `header.raw_json` + materiał dla pól gorących, §3.3/§3.5 — wyłuskanie należy
    do warstwy upsertu, krok §4.2).

Ten moduł NIE dotyka bazy (żadnego DML — meta-tripwir AST to potwierdza) i NIE zapisuje na
dysk usera (inwariant append-only, PLAN §6): FITS otwierany wyłącznie do odczytu, `memmap=False`
i bez sięgania po `.data`, więc na Windowsie nie zostaje uchwyt blokujący plik. `astropy` jest
PIERWSZĄ zależnością runtime Horreum — dochodzi właśnie z tym modułem (pyproject `dependencies`).
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from astropy.io import fits

from .hashing import sha1_of

# Rozszerzenia traktowane jako FITS. XISF/DSLR-raw to OSOBNE ścieżki/moduły (PLAN §4) — nie tu.
FITS_SUFFIXES = (".fits", ".fit", ".fts")

# Słowa-klucze nagłówkowe, które astropy zwraca wielokrotnie (komentarze/historia/puste).
# Akumulujemy je w listę, żeby zeznanie było 1:1 (nie gubimy powtórzeń przez kolizję klucza w dict).
_MULTI_KEYWORDS = ("COMMENT", "HISTORY", "")


@dataclass(frozen=True)
class ScanRecord:
    """Wynik skanu jednego pliku (read-only). Materiał wejściowy dla upsertu frame/location/header
    (krok §4.2) — sam w sobie nie jest zapisem domenowym."""
    path: str                         # ścieżka bezwzględna (str — spójnie z sha1_of/repo)
    sha1: str                         # tożsamość frame'a
    size_bytes: int
    mtime: str                        # ISO-8601 UTC (klucz przyszłego cache sha1, §7.9)
    header: dict = field(default_factory=dict)   # pełny nagłówek FITS, JSON-owalny


def iter_fits(root):
    """Przejdź drzewo `root` i wydaj ścieżki plików FITS (po rozszerzeniu, case-insensitive).

    Deterministycznie posortowane (powtarzalny skan/raport). Zwraca `Path`; pomija katalogi
    i pliki o innych rozszerzeniach. Nie podąża niczego nie modyfikując (czysty odczyt katalogu).
    """
    root = Path(root)
    return sorted(
        p for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() in FITS_SUFFIXES
    )


def _jsonable(value):
    """Sprowadź wartość karty FITS do typu JSON-owalnego. astropy zwraca bool/int/float/str
    oraz `Undefined` dla kart bez wartości — to ostatnie mapujemy na None."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, fits.Undefined):
        return None
    return str(value)                 # cokolwiek egzotycznego (np. complex) → tekst, byle wiernie


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
        if kw in _MULTI_KEYWORDS:
            out.setdefault(kw or "_BLANK", []).append(str(card.value))
        else:
            out[kw] = _jsonable(card.value)
    return out


def read_fits_header(path):
    """Odczytaj nagłówek FITS jako JSON-owalny dict. Read-only, bez ładowania pikseli, bez
    pozostawiania uchwytu (Windows). Podnosi wyjątek dla pliku, który nie jest FITS — faza
    skanu nie zgaduje (nierozstrzygalność trafia do `event(*.review)` w warstwie upsertu)."""
    with fits.open(path, mode="readonly", memmap=False) as hdul:
        return _header_to_dict(_select_header(hdul))


def scan_file(path):
    """Zeskanuj jeden plik FITS → `ScanRecord` (sha1 + stat + nagłówek). Czysty odczyt."""
    p = Path(path)
    st = p.stat()
    mtime = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat()
    return ScanRecord(
        path=str(p),
        sha1=sha1_of(str(p)),
        size_bytes=st.st_size,
        mtime=mtime,
        header=read_fits_header(str(p)),
    )
