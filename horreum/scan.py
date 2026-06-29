"""Skan drzewa FITS + XISF — primitivy read-only + pętla płaska skanu (PLAN §4; §Etap 1/§Etap 4).

Per plik produkuje TOŻSAMOŚĆ + ZEZNANIE nagłówka, niczego nie zapisując:
  - `sha1_of` (binarnie 'rb') = tożsamość frame'a (przeżywa rename/move),
  - `read_header` (dyspozytor) = pełny nagłówek jako JSON-owalny dict:
      * FITS (.fits/.fit/.fts) → astropy, read-only,
      * XISF (.xisf) → lekki czytnik stdlib (`struct` + `xml.etree`), bez nowej zależności.
    To przyszłe `header.raw_json` + materiał dla pól gorących (§3.3/§3.5) — wyłuskanie należy do
    warstwy upsertu (krok §4.2). UWAGA W3: XISF zwraca wartości jako STRINGI; rzut na typ robią
    dopiero pola gorące (§Etap 2), nie ten moduł.

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
import json
import struct
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from astropy.io import fits

from . import repo
from .hashing import sha1_of
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


def _unquote_fits(value):
    """Zdejmij FITS-owe cudzysłowy z wartości stringowej XISF (firsthand: PixInsight zapisuje karty
    stringowe jak FITS — `'ZWO ASI2600MC Pro'`). Apostrofy obejmujące zdejmowane, `''`→`'` (escape
    FITS), końcowe spacje → rstrip (nieznaczący pad FITS). Dzięki temu dict jest 1:1 z
    `read_fits_header` (astropy też zwraca string bez apostrofów). Liczby/bool (bez apostrofów)
    zostają NIETKNIĘTE — rzut na typ i tak robi `_to_float` (pola gorące, W3)."""
    if isinstance(value, str) and len(value) >= 2 and value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'").rstrip()
    return value


def read_xisf_header(path):
    """Odczytaj nagłówek XISF (monolithic) jako JSON-owalny dict — TEN SAM kontrakt co
    `read_fits_header` (klucze FITS wielkimi literami; COMMENT/HISTORY w listach), z jedną różnicą:
    wartości są STRINGAMI (XISF tak je trzyma; rzut na typ robią pola gorące — W3/§Etap 2).
    Wartości stringowe ODCUDZYSŁAWIANE z konwencji FITS (`_unquote_fits`, firsthand) — inaczej dict
    NIE byłby 1:1 z `read_fits_header` (astropy zwraca string bez apostrofów).

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
        _put(out, name.strip().upper(), _unquote_fits(elem.get("value", "")))
    return out


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
    """Zeskanuj jeden plik (FITS lub XISF) → `ScanRecord` (sha1 + stat + nagłówek). Czysty odczyt.

    Miękkie lądowanie (W1): nagłówek nieczytelny/nierozpoznany NIE przerywa skanu — `read_header`
    rzuca, my łapiemy i zwracamy `ScanRecord(header=None, error="Typ: opis")`. Tożsamość (`sha1`)
    i namiary pliku są wypełnione mimo to (frame i location powstaną; review nagłówka — wyżej).
    """
    p = Path(path)
    st = p.stat()
    mtime = _mtime_iso(st)
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
    (present=0, ten sam mtime) zostałby pominięty. Dziś `present` zawsze 1 — uśpione."""
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
    paths = iter_headers(root)
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
