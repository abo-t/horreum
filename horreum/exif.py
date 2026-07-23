"""Czytnik EXIF dla plików DSLR/RAW (.dng/.arw/.cr2) — TRZECI format wejścia obok FITS/XISF (#2).

Moduł WEJŚCIA, read-only, Qt-wolny (jak `scan.read_*`). Parsuje strukturę TIFF/EXIF stdlib-em
(`struct` + własny walk IFD, seek po offsetach) — ZERO nowej zależności (precedens XISF), ZERO
dekodowania pikseli (D-R-2). Produkuje dict o kluczach FITS-owych + karty (lustro 1:1), żeby pień
derywacji (`extract_header`/`camera_identity`/`normalize_kind`/`observatory`) jadł RAW BEZ ZMIAN (SPOT).

ZAKAZY (brief §0):
  * RAW jest READ-ONLY dla Horreum — writeback odmawia (`writeback._is_raw`), rename dozwolony.
  * NIE syntetyzujemy IMAGETYP (D-R-4): rodzaj RAW nie ma zeznania w EXIF; `kind` bierze się
    z FOLDERU (`kind_source='path'`) w `ingest_record`. Fabrykacja karty łamałaby „cards 1:1"
    i „nie zgadujemy" (`frames.py`).
  * Marker formatu NIE wchodzi do dict-a zeznania — `is_mono` dostaje `raw_format` z FAKTU
    rozszerzenia (ingest → `camera_identity(raw_format=…)`), nie ze sfabrykowanej karty.

TOŻSAMOŚĆ RAW = sha1 CAŁEGO pliku (D-R-1): RAW nigdy nie jest edytowany, a lokalizacja surowych
pikseli jest vendor-specyficzna (CR2 preview≠sensor, DNG SubIFD, ARW skompresowany) — hash pliku
jest odporny i wystarczający. `scan_file` podaje `span=(0, filesize)` → `sha1_data==file_sha1`,
`uncomputable=0` (NIE gałąź degeneracji — to INTENCJA, nie brak).
"""
import hashlib
import struct
from dataclasses import dataclass
from pathlib import Path

# Rozszerzenia RAW obsługiwane dziś — DOKŁADNIE te obecne i przetestowane w archiwum (763 klatki:
# 740 DNG + 69 ARW + 12 CR2, sonda 2026-07-23). NIE dokładamy nietestowanych formatów „na zapas"
# (SIN-PRECRUFT): CR3 to inny kontener (ISO-BMFF, nie TIFF); NEF/RAF/RW2 wejdą jednolinijkowo
# + test, gdy realnie się pojawią. Trzymamy lowercase (dopasowanie case-insensitive u wołającego).
RAW_SUFFIXES = (".dng", ".arw", ".cr2")

# TIFF: rozmiar bajtu per typ pola (1 BYTE, 2 ASCII, 3 SHORT, 4 LONG, 5 RATIONAL, 7 UNDEFINED,
# 9 SLONG, 10 SRATIONAL). Nieznany → 1 (bezpieczny odczyt surowych bajtów).
_TYPE_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 9: 4, 10: 8}

# Tagi TIFF/EXIF (stałe ID — vendor-agnostyczne). IFD0: aparat + wskaźniki na pod-IFD.
_MAKE, _MODEL, _DATETIME, _EXIF_IFD, _GPS_IFD = 0x010F, 0x0110, 0x0132, 0x8769, 0x8825
# ExifIFD: parametry ekspozycji.
_EXPTIME, _ISO, _DTO, _FOCAL, _LENS, _SUBSEC = 0x829A, 0x8827, 0x9003, 0x920A, 0xA434, 0x9291
# GPSIFD: pozycja (deg/min/sec jako RATIONAL ×3 + półkula).
_GPS_LATREF, _GPS_LAT, _GPS_LONREF, _GPS_LON = 1, 2, 3, 4

_TIFF_MAGIC = 42               # klasyczny TIFF; DNG/ARW/CR2 wszystkie niosą 42 (sonda)
_MAX_IFD_ENTRIES = 4096        # zdrowy sufit (realny IFD <200) — broni przed śmieciem/uszkodzeniem


@dataclass(frozen=True)
class ExifMeta:
    """Zeznanie EXIF wyłuskane z jednego otwarcia pliku RAW. `card_rows` = krotki
    `(keyword, idx, value_raw, value_num, value_type, comment)` — `scan_file` opakuje je w `Card`
    (unikamy cyklicznego importu `scan`). Lustro 1:1: `header` i `card_rows` powstają z JEDNEJ
    listy par, jak w XISF (rozjazd wymagałby dwóch pętli, a jest jedna)."""
    header: dict
    card_rows: list
    header_hash: str


def _read_value(fh, endian, typ, cnt, valoff):
    """Wartość pola IFD: ≤4 B siedzi w `valoff` wprost, inaczej `valoff` to offset (seek).
    RATIONAL/SRATIONAL o `cnt>1` (GPS: 3 składowe) zwracane listą. Read-only."""
    size = _TYPE_SIZE.get(typ, 1) * cnt
    if size <= 4:
        raw = valoff[:size]
    else:
        (off,) = struct.unpack(endian + "I", valoff)
        fh.seek(off)
        raw = fh.read(size)
    if typ == 2:                                  # ASCII (NUL-terminated)
        return raw.split(b"\x00")[0].decode("latin1", "replace").strip()
    if typ == 3:                                  # SHORT
        return struct.unpack(endian + "H", raw[:2])[0]
    if typ in (4, 9):                             # LONG / SLONG
        return struct.unpack(endian + ("i" if typ == 9 else "I"), raw[:4])[0]
    if typ in (5, 10):                            # (S)RATIONAL — może być wiele składowych
        fmt = endian + ("ii" if typ == 10 else "II")
        vals = []
        for i in range(cnt):
            chunk = raw[i * 8:i * 8 + 8]
            if len(chunk) < 8:
                break
            nu, de = struct.unpack(fmt, chunk)
            vals.append(nu / de if de else 0.0)
        if not vals:
            return None
        return vals if cnt > 1 else vals[0]
    return raw                                    # UNDEFINED/BYTE — surowe bajty


def _read_ifd(fh, off, endian, wanted):
    """Odczytaj wpisy IFD spod `off` dla tagów z `wanted` → {tag: wartość}. Wpisy czytamy w całości
    PRZED rozwiązywaniem wartości (seek w `_read_value` nie psuje pozycji). Podnosi przy podejrzanej
    liczbie wpisów (uszkodzony/nie-TIFF plik) → W1 w `scan_file`."""
    fh.seek(off)
    head = fh.read(2)
    if len(head) < 2:
        return {}
    (n,) = struct.unpack(endian + "H", head)
    if n > _MAX_IFD_ENTRIES:
        raise ValueError(f"IFD: podejrzana liczba wpisów ({n})")
    entries = fh.read(n * 12)
    out = {}
    for i in range(n):
        e = entries[i * 12:i * 12 + 12]
        if len(e) < 12:
            break
        tag, typ, cnt = struct.unpack(endian + "HHI", e[:8])
        if tag in wanted:
            out[tag] = _read_value(fh, endian, typ, cnt, e[8:12])
    return out


def _combine_instrume(make, model):
    """`Make`+`Model` → INSTRUME bez dublowania marki: Canon Model 'Canon EOS 40D' już niesie
    markę → INSTRUME=Model; Sony Model 'ILCE-7S' + Make 'SONY' → 'SONY ILCE-7S'."""
    make = (make or "").strip()
    model = (model or "").strip()
    if not model:
        return make or None
    if make and model.upper().startswith(make.upper()):
        return model
    return f"{make} {model}".strip() or None


def _date_obs(dt_str, subsec):
    """EXIF `DateTimeOriginal` ('2019:02:25 01:01:09') → FITS DATE-OBS ISO
    ('2019-02-25T01:01:09[.sub]'). `naming.header_dt` przyjmuje separator [T ] (SPOT). Śmieć → None."""
    s = (dt_str or "").strip()
    date, _, time = s.partition(" ")
    if len(date) != 10 or len(time) < 8:
        return None
    iso = date.replace(":", "-") + "T" + time[:8]
    sub = str(subsec).strip() if subsec not in (None, "") else ""
    return f"{iso}.{sub}" if sub.isdigit() else iso


def _gps_deg(dms, ref):
    """GPS (deg, min, sec) RATIONAL + półkula 'N/S/E/W' → stopnie dziesiętne ze znakiem
    (S/W = ujemne). site_coords ODRZUCA (0,0) (§4) — tu zwracamy wiernie, co niesie EXIF."""
    if dms is None:
        return None
    vals = list(dms) if isinstance(dms, (list, tuple)) else [dms]
    vals = (vals + [0.0, 0.0, 0.0])[:3]
    deg = vals[0] + vals[1] / 60.0 + vals[2] / 3600.0
    if isinstance(ref, str) and ref.strip().upper() in ("S", "W"):
        deg = -deg
    return deg


def read_exif_meta(path):
    """Odczytaj RAW (.dng/.arw/.cr2) → `ExifMeta` (dict FITS-owy + karty + header_hash). JEDNO
    otwarcie, read-only, seek po offsetach (DNG trzyma IFD0 na końcu pliku). Podnosi wyjątek dla
    pliku nie-TIFF / uszkodzonego — łapie `scan_file` (miękkie lądowanie W1), nie użytkownik.

    Wartości kart są STRINGAMI (`value_type='str'`, jak XISF) z projekcją liczbową w `value_num`
    — pień derywacji rzutuje przez `_to_float`/`_to_int` (W3), więc RAW i XISF nie rozjeżdżają osi."""
    with open(path, "rb") as fh:
        head = fh.read(8)
        if head[:2] == b"II":
            endian = "<"
        elif head[:2] == b"MM":
            endian = ">"
        else:
            raise ValueError(f"nie TIFF/RAW (bajty {head[:2]!r})")
        (magic,) = struct.unpack(endian + "H", head[2:4])
        if magic != _TIFF_MAGIC:
            raise ValueError(f"nie klasyczny TIFF (magic {magic})")
        (ifd0_off,) = struct.unpack(endian + "I", head[4:8])

        ifd0 = _read_ifd(fh, ifd0_off, endian, {_MAKE, _MODEL, _DATETIME, _EXIF_IFD, _GPS_IFD})
        exif = (_read_ifd(fh, ifd0[_EXIF_IFD], endian,
                          {_EXPTIME, _ISO, _DTO, _FOCAL, _LENS, _SUBSEC})
                if _EXIF_IFD in ifd0 else {})
        gps = (_read_ifd(fh, ifd0[_GPS_IFD], endian,
                         {_GPS_LATREF, _GPS_LAT, _GPS_LONREF, _GPS_LON})
               if _GPS_IFD in ifd0 else {})

    # ── Mapa EXIF → klucze FITS-owe (brief §3). JEDNA lista par → dict + karty (lustro 1:1). ──
    pairs = []                                    # (fits_keyword, value_str, value_num|None)

    def put(kw, value, num=None):
        if value is None or value == "":
            return
        pairs.append((kw, str(value), num))

    put("INSTRUME", _combine_instrume(ifd0.get(_MAKE), ifd0.get(_MODEL)))
    dto = exif.get(_DTO) or ifd0.get(_DATETIME)
    put("DATE-OBS", _date_obs(dto, exif.get(_SUBSEC)) if dto else None)
    exptime = exif.get(_EXPTIME)
    put("EXPTIME", exptime, exptime if isinstance(exptime, (int, float)) else None)
    put("GAIN", exif.get(_ISO))                   # ISO = gain DSLR; extract_header trzyma GAIN TEXT
    focal = exif.get(_FOCAL)
    if focal:                                     # 0 (obiektyw astro milczy) → pomijamy
        put("FOCALLEN", focal, focal if isinstance(focal, (int, float)) else None)
    lens = exif.get(_LENS)
    if lens and lens.strip("-"):                  # '----' (Sony: brak danych obiektywu) → pomijamy
        put("TELESCOP", lens)
    lat = _gps_deg(gps.get(_GPS_LAT), gps.get(_GPS_LATREF))
    lon = _gps_deg(gps.get(_GPS_LON), gps.get(_GPS_LONREF))
    if lat is not None and lon is not None:       # (0,0) wchodzi WIERNIE — site_coords je odrzuci (§4)
        put("SITELAT", lat, lat)
        put("SITELONG", lon, lon)

    header = {}
    card_rows = []
    for kw, sval, num in pairs:                   # każdy keyword unikalny → idx=0
        header[kw] = sval
        card_rows.append((kw, 0, sval, num, "str", None))
    header_hash = hashlib.sha1(
        "\n".join(f"{kw}={sval}" for kw, sval, _ in pairs).encode("utf-8")).hexdigest()
    return ExifMeta(header=header, card_rows=card_rows, header_hash=header_hash)


def read_exif_header(path):
    """Dict zeznania EXIF (kontrakt jak `read_fits_header`/`read_xisf_header`)."""
    return read_exif_meta(path).header


def is_raw(path):
    """Czy ścieżka to obsługiwany RAW (case-insensitive) — SPOT dla `scan._filetype`/dyspozytora."""
    return Path(path).suffix.lower() in RAW_SUFFIXES
