"""ŚLADY NA SUBACH - rdzeń wyszukiwania meteorów, satelitów i samolotów (brief/PLAN_meteory.md §2).

Czysty numpy (+ astropy do odczytu FITS): zero Qt, zero zapisu do bazy i do plików. Funkcje oddają
struktury w pamięci; zapis (baza albo raport w katalogu) należy do wołającego - drzwi zapisu raportu:
`horreum/raport.py` (`MT-2`).

METODA (Gural 2008 przeniesiony z wideo na suby; zmierzona w bramce Q0, `scripts/meteor_q0.py`):
  reszta   = sub - mediana ±2 sąsiadów sekwencji (wyrównanych korelacją fazową, przesunięcie CAŁKOWITE
             w skali binowanej - decyzja `Q0-b`) - tło grube (siatka 64 px binowana); σ z MAD
  maska    = reszta > k·σ (domyślnie 4σ - decyzja `Q0-a`) poza maską gwiazd, z co najmniej dwoma
             sąsiadami w otoczeniu 3×3; ramka marginesu wyrównania wycięta
  ślady    = transformata Hougha (0,5°, 2 px) + scalanie współliniowych odcinków jednej klatki
  pomiar   = profil wzdłuż śladu z pominięciem próbek pod maską gwiazd
  tory     = łączenie śladów kolejnych klatek (próg rosnący z odległością ekstrapolacji, 1:1 per strona)
  radiant  = test NIEUKIERUNKOWANY: odległość radiantu od koła wielkiego śladu; WCS wyłącznie
             z rozwiązania zewnętrznego (decyzja `Q0-c`: przybliżony WCS z `RA`/`DEC`/`OBJCTROT` odpada -
             obraz jest lustrzany, a `OBJCTROT` kłamie o ~4,5°); brak WCS = brak testu

JEDNOSTKI: współrzędne, długości i tolerancje na zewnątrz modułu są w pikselach NATYWNYCH (środki
pikseli, liczone od 0). Skala robocza (binowana) żyje wyłącznie w środku detektora, a przeliczenie
`min_len_native / bin` robi się dokładnie raz, w `hough_lines`. Piksel binowany `i` ma środek
w pikselu natywnym `i·bin + (bin-1)/2`.

PAMIĘĆ: `scan_sequence` trzyma w oknie najwyżej 2n+1 klatek binowanych (±2 sąsiadów), nie całą noc
(prototyp: ~8,7 GB na 1341 subów). Każda klatka jest czytana dokładnie raz.

PROGI KLASYFIKACJI (`END_SHARP`, `CV_SATELLITE`) pochodzą z wstrzyknięć Q0 (plan §1a ust. 5) - kształty
wstrzyknięć były założeniem o krzywej blasku meteoru, więc to hipoteza do potwierdzenia na prawdziwym
meteorze, nie pomiar. Próg okresowości samolotu (`BLINK_FAP`) nie był mierzony wcale - Q0 nie miało
samolotu; kalibruje go falsyfikator z wstrzyknięciem samolotu przerywanego.

PIKSEL NIESKOŃCZONY (NaN, inf - np. brzeg klatki po rejestracji): `np.median` niósł NaN do σ, a σ = NaN
dawało `skipped:no_noise` klatce i jej czterem sąsiadom, czyli całej sekwencji z NaN w każdej klatce.
`residual` liczy wtedy medianami `nan*` i dokłada takie piksele do maski (`stars`) - detekcja je
omija, pomiar profilu pomija. Klatki skończone idą drogą szybką (`np.median`), bez kosztu `nanmedian`.

TRYB KATALOGU (`scan_folder`, `report_files`): fakty sekwencji z nagłówków plików, detekcja w porcjach
sekwencji na `workers` wątkach, tory i klasy, raport jako bajty w pamięci (CSV, JSON, PNG pisany
stdlib `zlib` + `struct`). Zapis na dysk robi wołający przez drzwi `horreum/raport.py`. Wynik nie
zależy od `workers`: porcja czyta sąsiadów ze swojego brzegu, więc zbiór sąsiadów klatki jest ten sam.
"""
from __future__ import annotations

import contextlib
import csv
import hashlib
import io
import json
import math
import os
import struct
import warnings
import zlib
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from importlib import resources

import numpy as np
from astropy.io import fits

from . import exif, scan, sky
from .resolve._coerce import _to_float, _to_int, _to_text
from .resolve.frames import normalize_kind

# ---------------------------------------------------------------- parametry (zmierzone w Q0)

BIN = 4                      # binning roboczy (Q0 mierzyło przy 4)
K_SIGMA = 4.0                # próg detekcji w σ reszty (decyzja Q0-a)
MIN_LEN_NATIVE = 80.0        # najkrótszy ślad [px natywne]
N_NEIGHBOURS = 2             # sąsiedzi z każdej strony klatki: mediana z 2·N klatek
MIN_NEIGHBOURS = 2           # mniej sąsiadów = status `no_neighbours` (plan R6)
STAR_SIGMA = 8.0             # maska gwiazd: mediana sąsiadów > 8σ ...
STAR_DILATE = 2              # ... poszerzona o 2 px binowane
BG_CELL = 64                 # tło grube: siatka w px binowanych
ALIGN_MARGIN = 8             # ramka wycięta z detekcji ponad |przesunięcie| sąsiadów [px binowane]
OVERFLOW_FRACTION = 0.05     # więcej pikseli nad progiem = klatka nieanalizowalna (chmura, rozjazd);
                             # w prototypie 80 000 px na 1562×1044 binowanych = 4,9 %
HOUGH_THETA_STEP = 0.5       # krok kąta akumulatora [°]
HOUGH_RHO_BIN = 2.0          # kosz odległości akumulatora [px binowane]
HOUGH_NEAR = 2.5             # pas wokół prostej zbierający piksele odcinka [px binowane]
HOUGH_GAP = 12               # przerwa rozcinająca odcinek [px binowane] (dziury po gwiazdach)
HOUGH_FILL = 0.7             # najmniejsze wypełnienie odcinka pikselami
HOUGH_MAX_LINES = 6          # iteracyjnie zdejmowane proste na klatkę
MERGE_DTHETA = 1.0           # scalanie: |Δθ| [°] ...
MERGE_PERP = 3.0             # ... odległość końców od prostej [px binowane] (kosz rho ma 2 px) ...
MERGE_GAP_FRACTION = 0.1     # ... przerwa ≤ 10 % sumy długości
LINK_CADENCES = 3.0          # tory: Δt ≤ 3 × kadencja sekwencji
LINK_DTHETA = 3.0            # tory: |Δθ| [°]
LINK_DIST_MIN = 5.0          # tory: dolna granica progu odległości [px natywne]
LINK_SPEED_SPREAD = 0.2      # tory ≥ 3 klatek: (max - min) / mediana prędkości wzdłuż prostej
RADIANT_TOL = 3.0            # odległość radiantu od koła wielkiego śladu [°]
END_SHARP = 0.7              # koniec wewnątrz kadru jasny jak środek: satelita 0,96-0,97, meteor 0,26-0,42
CV_SATELLITE = 0.4           # CV profilu: satelita 0,22-0,26 (p90 ≤ 0,37), meteor 0,45-0,51
BLINK_FAP = 1e-3             # samolot: prawdopodobieństwo, że szczyt widma profilu to szum
PARALLEL_DTHETA = 1.0        # samolot: para równoległych śladów, |Δθ| [°] ...
PARALLEL_MAX = 20.0          # ... odległość prostych [px natywne]
SEQ_GAP_MIN = 600.0          # cięcie sekwencji: przerwa > max(10 min, 5 × mediana kadencji)
SEQ_GAP_CADENCES = 5.0
SEQ_EXPTIME_TOL = 0.10       # reżim ekspozycji: ten sam EXPTIME ±10 %
SEQ_ROTATION = 1.0           # cięcie sekwencji: zmiana OBJCTROT > 1° (flip, obrót kamery)
OBLIQUITY_J2000 = 23.4392911                 # nachylenie ekliptyki J2000 [°]
PRECESSION_LON = 0.013969697                 # precesja ogólna w długości [°/rok] (5029,0966″/stulecie)
DEG_PER_DAY_SUN = 360.0 / 365.2422           # przyrost długości ekliptycznej Słońca [°/dobę]
CHUNK_MIN, CHUNK_MAX = 25, 100   # porcja sekwencji na wątek: brzeg porcji czyta 2n klatek drugi raz
CROP_PAD = 16                    # wycinek: zapas wokół śladu [px binowane]
CROP_MAX = 512                   # dłuższy bok wycinka [px]; większy jest zmniejszany średnią z bloków
CROP_LO, CROP_HI = -2.0, 10.0    # rozciągnięcie reszty na wycinku [σ]
GUIDE_OFFSET = 6                 # linie prowadzące równolegle do śladu, po obu stronach [px binowane]
TILE = 160                       # kafel mozaiki [px]
MOSAIC_MAX = 400                 # kafli w mozaice (kolejność: kandydaci meteoru pierwsi)

_XISF_DTYPES = {"UInt8": "u1", "UInt16": "u2", "UInt32": "u4", "UInt64": "u8",
                "Float32": "f4", "Float64": "f8"}


# ---------------------------------------------------------------- odczyt pikseli

@dataclass(frozen=True)
class Binned:
    """Wynik `read_binned`. `status` = `ok` albo `skipped:*` / `error:*` (wtedy `data` = None)."""
    status: str
    data: object = None          # np.ndarray float32 (wys. // bin, szer. // bin) albo None
    bin: int = BIN
    native_shape: tuple = None   # (wys., szer.) w pikselach natywnych


def _bin_mean(a, b):
    """Średnia z bloków b×b; brzeg niepełnego bloku odcięty (piksele natywne poza nim nie istnieją
    dla detektora). Redukcja wprost na typie wejścia z akumulatorem float32 - bez kopii całej klatki."""
    ny, nx = a.shape[0] // b * b, a.shape[1] // b * b
    return a[:ny, :nx].reshape(ny // b, b, nx // b, b).mean(axis=(1, 3), dtype=np.float32)


def _parse_failure(exc):
    """Błąd, który mówi o PLIKU (format, uszkodzony nagłówek), a nie o systemie. `OSError` z kodem
    systemu (`errno`: brak dostępu, timeout SMB) jest przejściowy - leci do wołającego, który go
    ponawia; status `error:*` byłby wtedy trwałą etykietą na zdrowej klatce."""
    if isinstance(exc, OSError):
        return exc.errno is None
    return isinstance(exc, ValueError)


def _read_fits(path, bin_):
    """Pierwszy HDU z obrazem 2D (nie `scan._select_hdu`, który bierze pierwsze NAXIS>0); wartość
    fizyczna `surowa · BSCALE + BZERO` (astropy stosuje obie karty przy odczycie `.data`)."""
    with fits.open(path, memmap=False) as hdul:
        saw_cube = False
        for hdu in hdul:
            if not hdu.is_image:
                continue
            shape = tuple(hdu.shape)
            if len(shape) > 2:
                saw_cube = True
                continue
            if len(shape) != 2 or min(shape) < 1:
                continue
            if not isinstance(hdu, fits.CompImageHDU):
                # ucięty plik: astropy nie zgłasza tego wprost (kończy się `reshape` na złym rozmiarze)
                need = hdu.fileinfo()["datLoc"] + abs(int(hdu.header["BITPIX"])) // 8 * shape[0] * shape[1]
                if os.path.getsize(path) < need:
                    return Binned("error:truncated", bin=bin_, native_shape=shape)
            return Binned("ok", _bin_mean(hdu.data, bin_), bin_, shape)
        return Binned("skipped:fits_3d" if saw_cube else "error:no_image", bin=bin_)


def _read_xisf(path, bin_):
    """Piksele pierwszego `<Image>` wg `scan.xisf_image_descriptor`; RGB → luminancja (średnia
    kanałów). Kolejność bajtów przez dtype numpy, układ `planar` = (kanał, wys., szer.),
    `normal` = (wys., szer., kanał)."""
    desc = scan.xisf_image_descriptor(path)
    if desc is None:
        return Binned("error:no_image", bin=bin_)
    if desc["compression"]:
        return Binned("skipped:xisf_compressed", bin=bin_)
    if desc["span"] is None:
        return Binned("skipped:xisf_location", bin=bin_)
    if len(desc["geometry"]) != 3:
        return Binned("skipped:xisf_geometry", bin=bin_)
    kind = _XISF_DTYPES.get(desc["sample_format"])
    if kind is None:
        return Binned("skipped:xisf_sample_format", bin=bin_)
    width, height, channels = desc["geometry"]
    dtype = np.dtype(kind).newbyteorder("<" if desc["byte_order"] == "little" else ">")
    need = width * height * channels * dtype.itemsize
    start, size = desc["span"]
    if size < need:
        return Binned("error:parse", bin=bin_, native_shape=(height, width))
    with open(path, "rb") as fh:
        fh.seek(start)
        buf = fh.read(need)
    if len(buf) < need:
        return Binned("error:truncated", bin=bin_, native_shape=(height, width))
    a = np.frombuffer(buf, dtype=dtype)
    if desc["pixel_storage"] == "planar":
        planes = a.reshape(channels, height, width)
    else:
        planes = a.reshape(height, width, channels).transpose(2, 0, 1)
    if channels == 1:
        return Binned("ok", _bin_mean(planes[0], bin_), bin_, (height, width))
    lum = sum(_bin_mean(p, bin_) for p in planes) / np.float32(channels)
    return Binned("ok", lum.astype(np.float32), bin_, (height, width))


def read_binned(path, bin=BIN):
    """Klatka jako `float32` binowana średnią `bin×bin` + status. Format po rozszerzeniu (jak skan):
    FITS, XISF; RAW = `skipped:raw` (plan R4, `rawpy` dopiero w Q4); reszta = `skipped:format`.

    Statusy: `ok` · `skipped:fits_3d` · `skipped:xisf_compressed` · `skipped:xisf_location`
    (obraz poza blokiem `attachment`) · `skipped:xisf_geometry` · `skipped:xisf_sample_format` ·
    `skipped:raw` · `skipped:format` · `error:truncated` · `error:no_image` · `error:parse`.
    Przejściowy błąd I/O (`OSError` z kodem systemu) NIE jest statusem - leci do wołającego."""
    if bin < 1:
        raise ValueError(f"bin={bin} - musi być >= 1")
    suffix = os.path.splitext(str(path))[1].lower()
    if suffix in exif.RAW_SUFFIXES:
        return Binned("skipped:raw", bin=bin)
    if suffix not in scan.FITS_SUFFIXES + scan.XISF_SUFFIXES:
        return Binned("skipped:format", bin=bin)
    try:
        return (_read_xisf if suffix in scan.XISF_SUFFIXES else _read_fits)(path, bin)
    except (OSError, ValueError) as exc:
        if _parse_failure(exc):
            return Binned("error:parse", bin=bin)
        raise


# ---------------------------------------------------------------- sekwencje

@dataclass(frozen=True)
class FrameFacts:
    """Fakty klatki potrzebne do cięcia sekwencji. Tryb bazy bierze je z `header`, tryb katalogu
    z nagłówków plików (nie z nazwy katalogu). `ref` to identyfikator wołającego (ścieżka albo
    `frame_id`) - moduł go nie interpretuje. `time` = początek ekspozycji."""
    ref: object
    time: datetime
    exptime: float
    camera: object
    telescope: object
    filter: object
    width: int
    height: int
    binning: int
    channels: int = 1
    rotation: float = None       # OBJCTROT [°]; None = nieznany (nie tnie sekwencji)


def cadence(times):
    """Mediana odstępu między startami kolejnych klatek [s]; None przy mniej niż dwóch klatkach."""
    ts = sorted(times)
    deltas = [(b - a).total_seconds() for a, b in zip(ts, ts[1:])]
    deltas = [d for d in deltas if d > 0]
    return float(np.median(deltas)) if deltas else None


def _exposure_regimes(frames):
    """Klastry EXPTIME: nowy reżim, gdy czas naświetlania przekracza kotwicę reżimu o więcej niż
    10 %. Klaster, nie cięcie w czasie - przeplatane 60 s i 120 s tego samego filtra dają dwie
    sekwencje, nie serię jednoklatkowych."""
    known = sorted((f for f in frames if f.exptime is not None), key=lambda f: f.exptime)
    regimes, anchor = [], None
    for f in known:
        if anchor is None or f.exptime > anchor * (1 + SEQ_EXPTIME_TOL):
            regimes.append([])
            anchor = f.exptime
        regimes[-1].append(f)
    unknown = [f for f in frames if f.exptime is None]
    return regimes + ([unknown] if unknown else [])


def _rotation_jump(a, b):
    if a is None or b is None:
        return False
    return abs((a - b + 180.0) % 360.0 - 180.0) > SEQ_ROTATION


def sequences(frames):
    """Sekwencje w kolejności czasu. Klucz: kamera + teleskop + filtr + wymiary + binning + liczba
    kanałów + reżim ekspozycji. Cięcie: przerwa między startami > max(10 min, 5 × mediana kadencji)
    ALBO zmiana `OBJCTROT` > 1° (wyrównanie sąsiadów jest wyłącznie translacyjne). Obiekt NIE jest
    członem klucza - ta sama sekwencja bywa przypisana różnie, a niebo się nie zmienia."""
    groups = {}
    for f in frames:
        key = (f.camera, f.telescope, f.filter, f.width, f.height, f.binning, f.channels)
        groups.setdefault(key, []).append(f)
    out = []
    for members in groups.values():
        for regime in _exposure_regimes(members):
            regime = sorted(regime, key=lambda f: f.time)
            cad = cadence([f.time for f in regime])
            limit = max(SEQ_GAP_MIN, SEQ_GAP_CADENCES * cad) if cad else SEQ_GAP_MIN
            current = [regime[0]]
            for prev, f in zip(regime, regime[1:]):
                if (f.time - prev.time).total_seconds() > limit or _rotation_jump(prev.rotation, f.rotation):
                    out.append(current)
                    current = []
                current.append(f)
            out.append(current)
    out.sort(key=lambda s: s[0].time)
    return out


# ---------------------------------------------------------------- sąsiedzi i reszta

def neighbour_indices(i, count, n=N_NEIGHBOURS):
    """Indeksy 2n klatek najbliższych klatce `i` w sekwencji `count` klatek: ±n wewnątrz, przy
    brzegu dopełnione z drugiej strony (pierwsza klatka dostaje 1..2n, nie tylko dwie). Okno
    2n+1 kolejnych klatek zawierające `i`, dosunięte do brzegu sekwencji."""
    lo = max(0, min(i - n, count - 1 - 2 * n))
    return [j for j in range(lo, min(count, lo + 2 * n + 1)) if j != i]


def _clip(a):
    """Obraz do korelacji fazowej: tło zdjęte, przycięty do [0, p99,9]. Piksel nieskończony dostaje
    medianę klatki (NaN zalałby całą transformatę i przesunięcie wyszłoby z argmax po NaN)."""
    if not np.isfinite(a).all():
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)      # klatka cała NaN: mediana NaN
            a = np.where(np.isfinite(a), a, np.nanmedian(a))
        a = np.nan_to_num(a)
    a = a - np.median(a)
    return np.clip(a, 0, np.percentile(a, 99.9))


def phase_shift(ref, img):
    """Całkowite przesunięcie `(dy, dx)` w px binowanych, które nakłada `img` na `ref`
    (korelacja fazowa na obrazach przyciętych do [0, p99,9] - tło i gwiazdy nasycone nie ciągną)."""
    a, b = np.fft.rfft2(_clip(ref)), np.fft.rfft2(_clip(img))
    f = a * np.conj(b)
    cc = np.fft.irfft2(f / (np.abs(f) + 1e-9), s=ref.shape)
    py, px = np.unravel_index(int(cc.argmax()), cc.shape)
    dy = py - ref.shape[0] if py > ref.shape[0] / 2 else py
    dx = px - ref.shape[1] if px > ref.shape[1] / 2 else px
    return int(dy), int(dx)


def neighbours(i, frames, n=N_NEIGHBOURS):
    """Najbliższe 2n klatek `i` spośród dostępnych w `frames` (indeks → obraz binowany), każda
    wyrównana do klatki `i` korelacją fazową (przesunięcie całkowite, decyzja Q0-b).
    Zwraca listę `(j, obraz_wyrównany, (dy, dx))`."""
    ref = frames[i]
    near = sorted((j for j in frames if j != i), key=lambda j: (abs(j - i), j))[:2 * n]
    out = []
    for j in sorted(near):
        if frames[j].shape != ref.shape:
            raise ValueError(f"klatki {i} i {j} mają różne wymiary - klucz sekwencji ich nie rozdzielił")
        dy, dx = phase_shift(ref, frames[j])
        out.append((j, np.roll(np.roll(frames[j], dy, 0), dx, 1), (dy, dx)))
    return out


def _coarse_bg(r, cell=BG_CELL, median=np.median):
    """Tło grube: mediana w komórkach `cell`×`cell`, rozlana na piksele; brzeg niepełnej komórki
    bierze wartość ostatniej pełnej. `median` = `np.nanmedian` dla obrazu z pikselami NaN."""
    ny, nx = r.shape
    cell = max(1, min(cell, ny, nx))
    gy, gx = ny // cell, nx // cell
    g = median(r[:gy * cell, :gx * cell].reshape(gy, cell, gx, cell), axis=(1, 3))
    g = np.repeat(np.repeat(g, cell, 0), cell, 1)
    out = np.empty_like(r)
    out[:g.shape[0], :g.shape[1]] = g
    out[g.shape[0]:, :g.shape[1]] = g[-1:, :]
    out[:, g.shape[1]:] = out[:, g.shape[1] - 1:g.shape[1]]
    return out


def _dilate(m, k):
    out = m.copy()
    for dy in range(-k, k + 1):
        for dx in range(-k, k + 1):
            out |= np.roll(np.roll(m, dy, 0), dx, 1)
    return out


@dataclass(frozen=True)
class Residual:
    """Reszta klatki. `stars` jest OSOBNĄ maską (nie wyzerowaną w `r`): detekcja ją omija, a pomiar
    profilu pomija zamaskowane próbki zamiast liczyć je jako dziurę w śladzie."""
    r: object                    # np.ndarray float32, px binowane
    sigma: float                 # σ reszty z MAD
    stars: object                # np.ndarray bool (gwiazdy i piksele nieskończone)
    margin: int                  # ramka wycięta z detekcji [px binowane]
    bin: int


def residual(frame, neigh, bin=BIN):
    """`frame - mediana(sąsiedzi) - tło grube`; `neigh` = wynik `neighbours`. σ z MAD reszty; maska
    gwiazd z mediany sąsiadów (> 8σ, dylatacja 2 px); margines = max |przesunięcie| + 8.

    Piksel nieskończony w klatce albo u sąsiada: mediany `nan*` (sąsiad z NaN nie głosuje w swoim
    pikselu), a piksel reszty, który i tak wyszedł nieskończony, ma wartość 0 i trafia do maski."""
    stack = np.stack([a for _, a, _ in neigh])
    finite = bool(np.isfinite(frame).all() and np.isfinite(stack).all())
    median = np.median if finite else np.nanmedian
    # „All-NaN slice" daje NaN, który i tak idzie do maski. `catch_warnings` nie jest bezpieczne
    # między wątkami (globalne filtry), więc stoi wyłącznie na rzadkiej drodze nieskończonej.
    with contextlib.nullcontext() if finite else warnings.catch_warnings():
        if not finite:
            warnings.simplefilter("ignore", RuntimeWarning)
        med = median(stack, axis=0)
        r = frame - med
        r -= _coarse_bg(r, median=median)
        sigma = 1.4826 * float(median(np.abs(r - median(r))))
        stars = _dilate((med - _coarse_bg(med, median=median)) > STAR_SIGMA * sigma, STAR_DILATE)
    if not finite:
        bad = ~np.isfinite(r)
        r[bad] = 0.0
        stars |= bad
    margin = max((max(abs(dy), abs(dx)) for _, _, (dy, dx) in neigh), default=0) + ALIGN_MARGIN
    return Residual(r.astype(np.float32), sigma, stars, int(margin), bin)


def detection_mask(res, k_sigma=K_SIGMA):
    """Piksele kandydujące: reszta > k·σ poza maską gwiazd, co najmniej dwóch sąsiadów nad progiem
    w otoczeniu 3×3 (pojedyncze piksele i pary szumu odpadają), ramka marginesu wycięta."""
    m = np.where(res.stars, 0, res.r) > k_sigma * res.sigma
    count = sum(np.roll(np.roll(m, dy, 0), dx, 1).astype(np.int8)
                for dy in (-1, 0, 1) for dx in (-1, 0, 1)) - m
    m &= count >= 2
    g = res.margin
    m[:g, :] = False
    m[-g:, :] = False
    m[:, :g] = False
    m[:, -g:] = False
    return m


# ---------------------------------------------------------------- detekcja

def hough_lines(mask, min_len_native, bin=BIN):
    """Odcinki prostych w masce: akumulator (0,5°, 2 px), iteracyjne zdejmowanie do 6 prostych,
    na prostej najdłuższy odcinek z przerwami ≤ 12 px i wypełnieniem ≥ 0,7. Zwraca listę
    `(theta [rad], rho, ta, tb)` w px binowanych: prosta `x·cos θ + y·sin θ = rho`, odcinek od `ta`
    do `tb` wzdłuż kierunku `(-sin θ, cos θ)`.

    `min_len_native / bin` liczone TU i tylko tu (px natywne na wejściu - plan §0). Bramka długości
    liczy rozpiętość pikseli WŁĄCZNIE ze skrajnymi (`tb - ta + 1`): ślad pokrywający 20 pikseli ma
    20 px, a odległość środków skrajnych (19) odrzucała przy bin 4 5 z 28 jasnych śladów dokładnie
    80 px (sonda 2026-09-29: 10σ na piksel, 7 kątów × 4 ziarna). Współrzędne końców
    i `Streak.length` zostają na środkach pikseli. Ślad o prawdziwej długości blisko progu przechodzi
    zależnie od jasności: słabe końce spadają pod próg (80 px przy 3σ na piksel natywny mierzy się
    na 64-80 px)."""
    min_len = max(int(round(min_len_native / bin)), 5)
    ys, xs = np.nonzero(mask)
    if len(xs) < min_len:
        return []
    xs, ys = xs.astype(np.float32), ys.astype(np.float32)
    th = np.deg2rad(np.arange(0, 180, HOUGH_THETA_STEP)).astype(np.float32)
    c, s = np.cos(th), np.sin(th)
    diag = int(math.hypot(*mask.shape)) + 2
    nr = int(2 * diag / HOUGH_RHO_BIN) + 1
    cols = np.arange(len(th), dtype=np.int64)
    alive = np.ones(len(xs), bool)
    found = []
    for _ in range(HOUGH_MAX_LINES):
        idx = np.nonzero(alive)[0]
        if len(idx) < min_len:
            break
        x, y = xs[idx], ys[idx]
        acc = np.zeros(nr * len(th), np.int64)
        for k in range(0, len(x), 16384):          # porcje: pamięć akumulacji ograniczona
            ri = ((np.outer(x[k:k + 16384], c) + np.outer(y[k:k + 16384], s) + diag)
                  / HOUGH_RHO_BIN).astype(np.int64)
            acc += np.bincount((ri * len(th) + cols).ravel(), minlength=nr * len(th))
        best = int(acc.argmax())
        if acc[best] < min_len:
            break
        r0, t0 = divmod(best, len(th))
        rho0 = r0 * HOUGH_RHO_BIN - diag + HOUGH_RHO_BIN / 2
        near = np.abs(x * c[t0] + y * s[t0] - rho0) <= HOUGH_NEAR
        order = np.sort((-x * s[t0] + y * c[t0])[near])
        alive[idx[near]] = False
        gaps = np.nonzero(np.diff(order) > HOUGH_GAP)[0]
        starts, ends = np.r_[0, gaps + 1], np.r_[gaps, len(order) - 1]
        k = int(np.argmax(order[ends] - order[starts]))
        ta, tb = float(order[starts[k]]), float(order[ends[k]])
        npts = int(ends[k] - starts[k] + 1)
        # 0,01 px zapasu: rzut float32 na prostą osiową daje 19,999996 zamiast 20
        if tb - ta + 1 < min_len - 0.01 or npts / max(tb - ta, 1) < HOUGH_FILL:
            continue
        found.append((float(th[t0]), rho0, ta, tb))
    return found


def _seg_points(th, rho, ta, tb):
    c, s = math.cos(th), math.sin(th)
    return (rho * c - ta * s, rho * s + ta * c), (rho * c - tb * s, rho * s + tb * c)


def merge_segments(segs):
    """Scalanie współliniowych odcinków JEDNEJ klatki (Hough potrafi rozciąć jeden ślad na dwa
    sąsiednie kosze - klatka 86 nocy Perseidów): |Δθ| ≤ 1°, oba końce ≤ 3 px binowane od prostej
    dłuższego, przerwa wzdłużna ≤ 10 % sumy długości albo nakładka. Prosta scalonego = prosta
    dłuższego odcinka."""
    out = []
    for th, rho, ta, tb in sorted(segs, key=lambda q: -(q[3] - q[2])):
        for m in out:
            if abs((math.degrees(th - m[0]) + 90) % 180 - 90) > MERGE_DTHETA:
                continue
            p0, p1 = _seg_points(th, rho, ta, tb)
            c, s = math.cos(m[0]), math.sin(m[0])
            if any(abs(p[0] * c + p[1] * s - m[1]) > MERGE_PERP for p in (p0, p1)):
                continue
            t0, t1 = sorted((-p0[0] * s + p0[1] * c, -p1[0] * s + p1[1] * c))
            if max(t0 - m[3], m[2] - t1, 0) <= MERGE_GAP_FRACTION * ((m[3] - m[2]) + (t1 - t0)):
                m[2], m[3] = min(m[2], t0), max(m[3], t1)
                break
        else:
            out.append([th, rho, ta, tb])
    return [tuple(m) for m in out]


@dataclass(frozen=True)
class Streak:
    """Ślad jednej klatki. Współrzędne i długości w px NATYWNYCH (środki pikseli, od 0).

    `theta` = kąt NORMALNEJ prostej [°] (`x·cos θ + y·sin θ = rho`), jak w akumulatorze Hougha.
    `snr` = mediana profilu (średnia z 3 próbek poprzecznych / σ). `end0`/`end1` = jasność skrajnych
    10 % profilu względem środka (ostrość końca: ~1 = urwany ekspozycją, ≪ 1 = wygaszony) - None dla
    końca przy krawędzi kadru, bo krawędź tnie ślad jak ekspozycja (Z9). `edge_ends` = ile końców
    leży przy krawędzi. `blink_fap` = prawdopodobieństwo, że szczyt widma profilu to szum (małe =
    przerwy okresowe); `blink_period` = okres [px natywne]."""
    x0: float
    y0: float
    x1: float
    y1: float
    theta: float
    length: float
    width: float
    snr: float
    cv: float
    end0: float
    end1: float
    edge_ends: int
    masked_frac: float
    blink_fap: float
    blink_period: float


def _fwhm(profile, offsets):
    """FWHM profilu poprzecznego (interpolacja liniowa przejść przez połowę szczytu); None gdy
    szczyt nie wystaje nad tło albo profil nie opada do połowy w oknie."""
    base = float(np.median(profile[np.abs(offsets) >= offsets.max() - 1]))
    p = profile - base
    k = int(np.argmax(p))
    half = p[k] / 2
    if half <= 0:
        return None
    sides = []
    for step in (-1, 1):
        j = k
        while 0 <= j + step < len(p) and p[j + step] > half:
            j += step
        if not 0 <= j + step < len(p):
            return None
        a, b = p[j], p[j + step]
        sides.append(offsets[j] + step * (a - half) / (a - b))
    return float(sides[1] - sides[0])


def _blink(profile):
    """Okresowość profilu: szczyt widma mocy (bez składowych 0-2, które niesie łagodna krzywa
    blasku meteoru) względem średniej mocy; `fap` = 1 - (1 - e^-z)^M dla białego szumu przy M
    częstościach. Krótszy profil niż 16 próbek - brak testu."""
    n = len(profile)
    if n < 16:
        return None, None
    power = np.abs(np.fft.rfft(profile - profile.mean())) ** 2
    band = power[3:]
    if band.size == 0 or band.mean() <= 0:
        return None, None
    k = int(np.argmax(band))
    z = float(band[k] / band.mean())
    fap = 1.0 - (1.0 - math.exp(-z)) ** band.size
    return fap, n / (k + 3)


def measure(seg, res):
    """Miary odcinka `seg` (wynik `hough_lines`/`merge_segments`) na reszcie `res`. Profil to suma
    trzech próbek poprzecznych w każdym pikselu wzdłuż śladu; próbki pod maską gwiazd są pomijane
    (maska wycina dziury w śladzie - wliczone udawałyby niestałą jasność)."""
    th, rho, ta, tb = seg
    (x0, y0), (x1, y1) = _seg_points(th, rho, ta, tb)
    n = max(int(tb - ta) + 1, 2)
    xs, ys = np.linspace(x0, x1, n), np.linspace(y0, y1, n)
    nx, ny = math.cos(th), math.sin(th)
    H, W = res.r.shape
    b = res.bin

    def sample(off):
        xi = np.clip(np.round(xs + off * nx).astype(int), 0, W - 1)
        yi = np.clip(np.round(ys + off * ny).astype(int), 0, H - 1)
        return res.r[yi, xi], res.stars[yi, xi]

    core = np.zeros(n)
    masked = np.zeros(n, bool)
    for off in (-1, 0, 1):
        v, m = sample(off)
        core += v
        masked |= m
    prof = core / (3 * res.sigma)
    ok = ~masked
    use = ok if ok.sum() >= 5 else np.ones(n, bool)     # ślad prawie cały pod gwiazdami: bierz wszystko
    p = prof[use]
    q = max(len(p) // 10, 1)
    mid = float(np.median(p[q:-q])) if len(p) > 2 * q else float(np.median(p))

    offsets = np.arange(-6, 7)
    width_b = _fwhm(np.array([float(np.median(sample(o)[0][use])) for o in offsets]), offsets)

    # koniec przy krawędzi: detekcja nie widzi ramki marginesu, więc „krawędź" zaczyna się na niej;
    # zapas 3 szerokości śladu (plan §2), co najmniej 3 px
    margin = res.margin + 3 * max(1.0, width_b or 1.0)

    def inside(x, y):
        return margin < x < W - 1 - margin and margin < y < H - 1 - margin

    ends = [round(float(np.mean(part)) / max(mid, 1e-6), 3) if inside(x, y) else None
            for x, y, part in ((x0, y0, p[:q]), (x1, y1, p[-q:]))]
    fap, period = _blink(np.where(ok, prof, float(np.median(p))))

    def nat(v):
        return v * b + (b - 1) / 2

    return Streak(x0=nat(x0), y0=nat(y0), x1=nat(x1), y1=nat(y1), theta=math.degrees(th),
                  length=(tb - ta) * b, width=None if width_b is None else round(width_b * b, 2),
                  snr=round(mid, 2), cv=round(float(p.std() / max(abs(p.mean()), 1e-6)), 3),
                  end0=ends[0], end1=ends[1], edge_ends=sum(e is None for e in ends),
                  masked_frac=round(float(masked.mean()), 3),
                  blink_fap=None if fap is None else float(fap),
                  blink_period=None if period is None else round(period * b, 1))


def render_crop(seg, res):
    """Wycinek reszty wokół odcinka `seg` (wynik `merge_segments`, px binowane) do oceny okiem:
    reszta rozciągnięta liniowo od -2σ do 10σ na szarość, dwie czerwone linie prowadzące
    równolegle do śladu `GUIDE_OFFSET` px wycinka po obu stronach - linia NA śladzie zasłoniłaby to,
    co człowiek ma ocenić (końce, mruganie). Dłuższy bok ponad `CROP_MAX` - zmniejszenie średnią
    z bloków (odstęp linii rośnie wtedy w pikselach binowanych, żeby po zmniejszeniu nie zlały się
    ze śladem). Zwraca RGB `uint8` (wys., szer., 3)."""
    th, rho, ta, tb = seg
    (x0, y0), (x1, y1) = _seg_points(th, rho, ta, tb)
    H, W = res.r.shape
    pad = CROP_PAD + GUIDE_OFFSET
    xa, xb = max(0, int(min(x0, x1)) - pad), min(W, int(max(x0, x1)) + pad + 1)
    ya, yb = max(0, int(min(y0, y1)) - pad), min(H, int(max(y0, y1)) + pad + 1)
    f = max(1, math.ceil(max(xb - xa, yb - ya) / CROP_MAX))
    crop = res.r[ya:yb, xa:xb] / np.float32(res.sigma)
    if f > 1:
        crop = _bin_mean(crop, f)
    gray = np.clip((crop - CROP_LO) * (255.0 / (CROP_HI - CROP_LO)), 0, 255).astype(np.uint8)
    img = np.repeat(gray[:, :, None], 3, axis=2)
    c, s = math.cos(th), math.sin(th)
    t = np.arange(ta, tb + 0.5, 0.5)
    for off in (-GUIDE_OFFSET * f, GUIDE_OFFSET * f):     # odstęp stały w pikselach WYCINKA
        xi = np.floor(((rho + off) * c - t * s - xa) / f).astype(int)
        yi = np.floor(((rho + off) * s + t * c - ya) / f).astype(int)
        ok = (xi >= 0) & (xi < img.shape[1]) & (yi >= 0) & (yi < img.shape[0])
        img[yi[ok], xi[ok]] = (255, 40, 40)
    return img


@dataclass(frozen=True)
class FrameResult:
    """Wynik jednej klatki sekwencji. `status`: `done` · `no_neighbours` · `skipped:no_noise`
    (reszta zerowa - np. ta sama klatka dwa razy) · `skipped:overflow` (zbyt wiele pikseli nad
    progiem) · `error:shape` (kształt danych obcy w oknie albo klatka pusta po binningu) · statusy
    `read_binned`. `hough_segments` liczy odcinki PRZED scaleniem - raport
    podaje osobno `hough_segments`, `streaks` i `tracks`. `crops` (na żądanie, `crops=True`) - wycinek
    reszty RGB `uint8` z liniami prowadzącymi, po jednym na ślad, w kolejności `streaks`."""
    index: int
    status: str
    streaks: tuple = ()
    hough_segments: int = 0
    sigma: float = None
    margin: int = None
    n_neighbours: int = 0
    crops: tuple = ()


def detect_frame(index, frame, neigh, *, k_sigma=K_SIGMA, min_len_native=MIN_LEN_NATIVE, bin=BIN,
                 crops=False):
    """Detekcja na klatce `frame` (binowanej) z sąsiadami `neigh` (wynik `neighbours`). `crops` -
    dołącz wycinki reszty (`render_crop`); reszta klatki nie przeżywa wywołania, więc wycinek
    powstaje tu albo wcale."""
    if len(neigh) < MIN_NEIGHBOURS:
        return FrameResult(index, "no_neighbours", n_neighbours=len(neigh))
    res = residual(frame, neigh, bin)
    if not res.sigma > 0:
        return FrameResult(index, "skipped:no_noise", n_neighbours=len(neigh))
    mask = detection_mask(res, k_sigma)
    if mask.sum() > OVERFLOW_FRACTION * mask.size:
        return FrameResult(index, "skipped:overflow", sigma=res.sigma, margin=res.margin,
                           n_neighbours=len(neigh))
    segs = hough_lines(mask, min_len_native, bin)
    merged = merge_segments(segs)
    streaks = tuple(measure(s, res) for s in merged)
    images = tuple(render_crop(s, res) for s in merged) if crops else ()
    return FrameResult(index, "done", streaks, len(segs), res.sigma, res.margin, len(neigh), images)


def scan_sequence(count, load, *, start=0, stop=None, n=N_NEIGHBOURS, k_sigma=K_SIGMA,
                  min_len_native=MIN_LEN_NATIVE, bin=BIN, crops=False):
    """Detekcja na klatkach `start..stop-1` sekwencji `count` klatek (domyślnie całej) w oknie
    przesuwnym: `load(j)` → `Binned` klatki j (wołający wie, skąd ją wziąć). W pamięci najwyżej
    2n+1 klatek; każda czytana raz, bo okno `neighbour_indices` przesuwa się monotonicznie. Sąsiedzi
    klatki zależą od `count`, nie od porcji - porcja sekwencji daje te same wyniki co przebieg
    całości (tryb katalogu dzieli tak sekwencję między wątki). Klatka nieczytelna nie jest
    sąsiadem - bierze się wtedy mniej sąsiadów, a przy mniej niż `MIN_NEIGHBOURS` klatka dostaje
    `no_neighbours`. Rozjazd kształtu degraduje klatkę, nie sekwencję (`_window_result`).
    Generator `FrameResult` w kolejności klatek."""
    window = {}
    for i in range(start, count if stop is None else stop):
        need = set(neighbour_indices(i, count, n)) | {i}
        for j in [j for j in window if j not in need]:
            del window[j]
        for j in sorted(need - window.keys()):
            window[j] = load(j)
        yield _window_result(i, window, n, k_sigma, min_len_native, bin, crops)


def _window_result(i, window, n, k_sigma, min_len_native, bin, crops=False):
    """Wynik klatki `i` z okna. Osobna funkcja, bo lokalne referencje do klatek giną przy powrocie -
    w pętli generatora przeżyłyby do następnego odczytu i okno trzymałoby o klatkę więcej.

    Klucz sekwencji grupuje po wymiarach z nagłówka, a kształt pochodzi z danych pliku (plik
    podmieniony po skanie, nagłówek inny niż dane), więc w oknie może stanąć klatka obcego kształtu.
    Klatka dostaje `error:shape`, gdy po binningu nie ma pikseli albo gdy inny kształt ma w oknie
    więcej czytelnych klatek niż jej własny; sąsiadem jest tylko klatka tego samego kształtu. Obcy
    to mniejszość okna, nie „inny niż pierwsza klatka" - seria zmieniająca kształt w połowie liczy
    obie połowy."""
    own = window[i]
    if own.status != "ok":
        return FrameResult(i, own.status)
    shapes = Counter(w.data.shape for w in window.values() if w.status == "ok" and w.data.size)
    if not own.data.size or shapes[own.data.shape] < max(shapes.values()):
        return FrameResult(i, "error:shape")
    readable = {j: w.data for j, w in window.items() if w.status == "ok" and w.data.shape == own.data.shape}
    return detect_frame(i, own.data, neighbours(i, readable, n), k_sigma=k_sigma,
                        min_len_native=min_len_native, bin=bin, crops=crops)


# ---------------------------------------------------------------- tory

def link_tolerance(extrap, bin=BIN):
    """Próg odległości końca śladu od prostej poprzednika [px natywne] przy ekstrapolacji `extrap`
    [px natywne, od środka odcinka poprzednika]. Prosta z Hougha to środek kosza: kąt myli się
    o jeden kosz kąta (0,5°), odległość o pół kosza rho (1 px binowany = `bin` px natywnych). Pół
    kosza kąta nie daje zapasu: na torach nocy Perseidów ogniwo 36→37 przechodzi wtedy przy
    d/próg = 0,999, a 86→87 (16 px przy ~2980 px ekstrapolacji, 0,31° przy zerowym przesunięciu)
    przy 0,94; pełny kosz daje co najmniej 1,38× zapasu (plan §1a, dopisek Q1). Dolna granica 5 px."""
    return max(LINK_DIST_MIN, bin * HOUGH_RHO_BIN / 2 + extrap * math.tan(math.radians(HOUGH_THETA_STEP)))


def _end_offset(a, b):
    """Najmniejsza odległość końca `b` od prostej `a` i odległość tego końca od środka `a` wzdłuż
    prostej (ekstrapolacja)."""
    th = math.radians(a.theta)
    c, s = math.cos(th), math.sin(th)
    rho = a.x0 * c + a.y0 * s
    mx, my = (a.x0 + a.x1) / 2, (a.y0 + a.y1) / 2
    return min((abs(x * c + y * s - rho), abs(-(x - mx) * s + (y - my) * c))
               for x, y in ((b.x0, b.y0), (b.x1, b.y1)))


def _speed(a, b, dt):
    """Prędkość wzdłuż prostej `a`: przesunięcie środków rzutowane na kierunek śladu / Δt [px/s]."""
    th = math.radians(a.theta)
    dx = (b.x0 + b.x1 - a.x0 - a.x1) / 2
    dy = (b.y0 + b.y1 - a.y0 - a.y1) / 2
    return abs(-dx * math.sin(th) + dy * math.cos(th)) / dt


@dataclass(frozen=True)
class Tracks:
    """Wynik `link_tracks`; liczby to indeksy w liście wejściowej. `tracks` - łańcuchy ≥ 2 śladów
    w kolejności czasu; `ambiguous` - ślady bez toru, które przegrały konflikt przypisania 1:1
    (mogły być ciągiem cudzego toru - do oceny człowieka, nie automatu)."""
    links: tuple = ()
    tracks: tuple = ()
    ambiguous: tuple = ()


def link_tracks(items, cadence, bin=BIN):
    """Tory satelitów przez kolejne klatki sekwencji. `items` = lista `(klatka, t, Streak)`: numer
    klatki w sekwencji, czas startu [s] (dowolne zero), ślad. `cadence` = mediana kadencji [s];
    brak kadencji (None - `cadence()` przy mniej niż dwóch różnych czasach - albo ≤ 0) = brak torów,
    bo bez niej nie ma progu Δt.

    Kandydaci: kolejne klatki ZE śladami, Δt ≤ 3 × kadencja, |Δθ| ≤ 3°, koniec następnika w odległości
    ≤ `link_tolerance(ekstrapolacja)` od prostej poprzednika. Przypisanie zachłanne po koszcie
    `|Δθ| + d / próg`, 1:1 PER STRONA (najwyżej jeden następnik i jeden poprzednik - wspólny zbiór
    „użytych" blokował następnikowi zostanie poprzednikiem i rwał tor). Tor ≥ 3 klatek: rozrzut
    prędkości wzdłuż prostej ≤ 20 % mediany, inaczej ogniwo odpada.

    Współrzędne są porównywane w układach klatek bez korekty ditheringu - Δt ≤ 3 kadencje nie
    przepuszcza ogniw przez przerwę na dithering serii krótkich, a na subach długich satelita mieści
    się w jednej klatce (plan §1a ust. 6)."""
    if cadence is None or not cadence > 0:
        return Tracks()
    by_frame = {}
    for k, (frame, _, _) in enumerate(items):
        by_frame.setdefault(frame, []).append(k)
    frames = sorted(by_frame)
    nxt, prv, speeds, contested = {}, {}, {}, set()
    for fa, fb in zip(frames, frames[1:]):
        dt = items[by_frame[fb][0]][1] - items[by_frame[fa][0]][1]
        if dt <= 0 or dt > LINK_CADENCES * cadence:
            continue
        cands = []
        for a in by_frame[fa]:
            sa = items[a][2]
            for b in by_frame[fb]:
                sb = items[b][2]
                dth = abs((sa.theta - sb.theta + 90) % 180 - 90)
                if dth > LINK_DTHETA:
                    continue
                d, extrap = _end_offset(sa, sb)
                tol = link_tolerance(extrap, bin)
                if d <= tol:
                    cands.append((dth + d / tol, a, b))
        for _, a, b in sorted(cands):
            if a in nxt or b in prv:
                contested.update((a, b))
                continue
            chain = speeds.get(a, []) + [_speed(items[a][2], items[b][2], dt)]
            if len(chain) >= 2 and (max(chain) - min(chain)) > LINK_SPEED_SPREAD * float(np.median(chain)):
                continue
            nxt[a], prv[b], speeds[b] = b, a, chain
    tracks = []
    for k in sorted(nxt):
        if k in prv:
            continue
        chain = [k]
        while chain[-1] in nxt:
            chain.append(nxt[chain[-1]])
        tracks.append(tuple(chain))
    in_track = {k for t in tracks for k in t}
    return Tracks(links=tuple(sorted(nxt.items())), tracks=tuple(tracks),
                  ambiguous=tuple(sorted(contested - in_track)))


# ---------------------------------------------------------------- radiant

def load_showers():
    """Lista rojów z assetu `horreum/data/meteor_showers.json` (IAU MDC, `scripts/build_showers.py`).
    Brak assetu to błąd instalacji, nie pusta lista."""
    raw = resources.files("horreum.data").joinpath("meteor_showers.json").read_text(encoding="utf-8")
    return json.loads(raw)["showers"]


def _unit(ra, dec):
    a, d = math.radians(ra), math.radians(dec)
    return np.array([math.cos(d) * math.cos(a), math.cos(d) * math.sin(a), math.sin(d)])


def _eq_to_ecl(ra, dec):
    e = math.radians(OBLIQUITY_J2000)
    a, d = math.radians(ra), math.radians(dec)
    lam = math.atan2(math.sin(a) * math.cos(e) + math.tan(d) * math.sin(e), math.cos(a))
    beta = math.asin(math.sin(d) * math.cos(e) - math.cos(d) * math.sin(e) * math.sin(a))
    return math.degrees(lam) % 360, math.degrees(beta)


def _ecl_to_eq(lam, beta):
    e = math.radians(OBLIQUITY_J2000)
    lm, b = math.radians(lam), math.radians(beta)
    ra = math.atan2(math.sin(lm) * math.cos(e) - math.tan(b) * math.sin(e), math.cos(lm))
    dec = math.asin(math.sin(b) * math.cos(e) + math.cos(b) * math.sin(e) * math.sin(lm))
    return math.degrees(ra) % 360, math.degrees(dec)


def solar_longitude(when):
    """Długość ekliptyczna Słońca J2000 [°] - układ list IAU MDC. Model Słońca bierze `sky`
    (jeden właściciel); tu tylko rzut na ekliptykę i zdjęcie precesji od J2000. `when` MUSI być
    aware (jak w `sky`)."""
    jd = sky._jd(when)
    lam, _ = _eq_to_ecl(*sky._sun_radec(jd))
    return (lam - PRECESSION_LON * (jd - 2451545.0) / 365.25) % 360


def _active(shower, lam):
    lo, hi = shower["los_begin"], shower["los_end"]
    return lo <= lam <= hi if lo <= hi else (lam >= lo or lam <= hi)


def radiant_at(shower, lam):
    """Radiant roju przy długości Słońca `lam` [°]: pozycja w maksimum + dryf dzienny z listy. Rój
    bez zmierzonego dryfu (`drift_estimated`) - dryf szacowany: radiant stały w układzie ekliptycznym
    związanym ze Słońcem (λ - λ☉ i β bez zmian), zamiast udawać zerowy ruch."""
    dlam = (lam - shower["los"] + 180.0) % 360.0 - 180.0
    if shower.get("dra") is not None and shower.get("ddec") is not None:
        days = dlam / DEG_PER_DAY_SUN
        return (shower["ra"] + shower["dra"] * days) % 360, shower["dec"] + shower["ddec"] * days
    el, eb = _eq_to_ecl(shower["ra"], shower["dec"])
    return _ecl_to_eq(el + dlam, eb)


def radiant_match(streak, wcs, date_obs, showers, tol=RADIANT_TOL):
    """Test NIEUKIERUNKOWANY (sub nie niesie kierunku ruchu): odległość radiantu aktywnego roju od
    koła wielkiego przez końce śladu ≤ `tol` stopni, po dryfie radiantu na `date_obs` (aware).

    `wcs` = rozwiązanie astrometryczne klatki z ZEWNĄTRZ (np. `astropy.wcs.WCS` z pliku `.wcs`
    ASTAP; wystarczy metoda `all_pix2world`), w pikselach natywnych od 0. Brak WCS → None (brak
    testu, nie „brak roju"). Wynik: lista `(kod, odległość [°])` rosnąco po odległości; pusta =
    test wykonany, żaden rój nie pasuje. Przypadkowe koło wielkie mija dany punkt o ≤ 3° z p ≈ 5 %
    (plan §1a ust. 9) - radiant wspiera, nie rozstrzyga."""
    if wcs is None:
        return None
    (ra0, dec0), (ra1, dec1) = wcs.all_pix2world(
        np.array([[streak.x0, streak.y0], [streak.x1, streak.y1]], dtype=float), 0)
    pole = np.cross(_unit(ra0, dec0), _unit(ra1, dec1))
    norm = float(np.linalg.norm(pole))
    if norm == 0:
        return None
    pole /= norm
    lam = solar_longitude(date_obs)
    out = []
    for sh in showers:
        if not _active(sh, lam):
            continue
        dist = math.degrees(math.asin(min(1.0, abs(float(pole @ _unit(*radiant_at(sh, lam)))))))
        if dist <= tol:
            out.append((sh["code"], round(dist, 3)))
    return sorted(out, key=lambda m: m[1])


# ---------------------------------------------------------------- klasyfikacja

def parallel_partners(streaks):
    """Indeksy śladów JEDNEJ klatki, które mają równoległego partnera (|Δθ| ≤ 1°, prosta ≤ 20 px
    natywnych, nakładka wzdłuż śladu) - para świateł samolotu."""
    out = set()
    for i, a in enumerate(streaks):
        th = math.radians(a.theta)
        c, s = math.cos(th), math.sin(th)
        rho = a.x0 * c + a.y0 * s
        ta = sorted((-a.x0 * s + a.y0 * c, -a.x1 * s + a.y1 * c))
        for j, b in enumerate(streaks):
            if j == i or abs((a.theta - b.theta + 90) % 180 - 90) > PARALLEL_DTHETA:
                continue
            mx, my = (b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2
            tb = sorted((-b.x0 * s + b.y0 * c, -b.x1 * s + b.y1 * c))
            if abs(mx * c + my * s - rho) <= PARALLEL_MAX and min(ta[1], tb[1]) > max(ta[0], tb[0]):
                out.add(i)
    return out


def classify(streak, *, track_len=1, parallel=False, showers=None):
    """Propozycja klasy (werdykt automatu NIE jest werdyktem człowieka), w tej kolejności:
    `samolot` (przerwy okresowe albo równoległy partner) · `satelita` (tor ≥ 2 klatek ALBO oba końce
    wewnątrz kadru ostre przy niskim CV) · `meteor:<rój>` (`showers` = wynik `radiant_match` niepusty)
    · `meteor?` (niestała jasność albo łagodny koniec wewnątrz kadru) · `nieokreslony`
    (np. ślad przez cały kadr o stałej jasności - bez końców satelity od meteoru nie odróżnić)."""
    if parallel or (streak.blink_fap is not None and streak.blink_fap < BLINK_FAP):
        return "samolot"
    if track_len >= 2:
        return "satelita"
    inside = [e for e in (streak.end0, streak.end1) if e is not None]
    if len(inside) == 2 and min(inside) >= END_SHARP and streak.cv < CV_SATELLITE:
        return "satelita"
    if showers:
        return f"meteor:{showers[0][0]}"
    if streak.cv >= CV_SATELLITE or any(e < END_SHARP for e in inside):
        return "meteor?"
    return "nieokreslony"


# ---------------------------------------------------------------- PNG (stdlib)

def png_bytes(img):
    """Obraz `uint8` - szarość (wys., szer.) albo RGB (wys., szer., 3) - jako bajty PNG. Stdlib
    (`zlib` + `struct`), bez Qt i PIL: CLI działa bez extras `gui` (plan §0)."""
    img = np.ascontiguousarray(img, dtype=np.uint8)
    if img.ndim == 2:
        colour = 0
    elif img.ndim == 3 and img.shape[2] == 3:
        colour = 2
    else:
        raise ValueError(f"PNG: kształt {img.shape} - oczekiwana szarość albo RGB")
    h, w = img.shape[:2]
    if not h or not w:
        raise ValueError("PNG: obraz pusty")
    rows = np.concatenate([np.zeros((h, 1), np.uint8), img.reshape(h, -1)], axis=1)   # filtr 0

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, colour, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows.tobytes(), 6)) + chunk(b"IEND", b""))


def _tile(img):
    """Wycinek wpisany w kafel `TILE`×`TILE` (najbliższy sąsiad, proporcje zachowane, czarne pola)."""
    h, w = img.shape[:2]
    k = min(TILE / h, TILE / w)
    nh, nw = max(1, int(h * k)), max(1, int(w * k))
    yi = np.minimum((np.arange(nh) / k).astype(int), h - 1)
    xi = np.minimum((np.arange(nw) / k).astype(int), w - 1)
    tile = np.zeros((TILE, TILE, 3), np.uint8)
    oy, ox = (TILE - nh) // 2, (TILE - nw) // 2
    tile[oy:oy + nh, ox:ox + nw] = img[yi][:, xi]
    return tile


def mosaic(images):
    """Kafle wycinków w siatce prawie kwadratowej, 2 px szarej przerwy. Pusta lista = None."""
    if not images:
        return None
    cols = math.ceil(math.sqrt(len(images)))
    rows = math.ceil(len(images) / cols)
    step = TILE + 2
    out = np.full((rows * step + 2, cols * step + 2, 3), 64, np.uint8)
    for n, img in enumerate(images):
        r, c = divmod(n, cols)
        out[2 + r * step:2 + r * step + TILE, 2 + c * step:2 + c * step + TILE] = _tile(img)
    return out


# ---------------------------------------------------------------- tryb katalogu

def folder_inputs(folder):
    """Pliki klatek pod `folder`, posortowane: FITS, XISF i RAW (RAW dostaje `skipped:raw`, ale raport
    go liczy - „nieliczone" ma być widoczne), drzewa robocze `_WBPP`/`_Review` odcięte jak w skanie
    (`scan.iter_headers`). Zwraca `(ścieżki, katalogi nieprzeczytane)` - nieprzeczytany katalog
    jest w raporcie, nie znika po cichu."""
    errors = []
    return [str(p) for p in scan.iter_headers(folder, errors_out=errors)], errors


def _date_obs(value):
    """`DATE-OBS` → naiwny `datetime` (strefy nie zgadujemy - sekwencje i tory liczą różnice czasu);
    ułamek sekundy dowolnej długości obcięty do mikrosekund. Brak albo inny zapis → None."""
    text = _to_text(value)
    if text is None or len(text) < 19 or text[10] not in "T ":
        return None
    try:
        t = datetime.strptime(text[:19].replace(" ", "T"), "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None
    frac = text[19:]
    if frac.startswith("."):
        digits = frac[1:7]
        if not digits.isdigit():
            return None
        t = t.replace(microsecond=int(digits.ljust(6, "0")))
    return t


def folder_facts(path):
    """Fakty sekwencji z nagłówka pliku → `(FrameFacts, None)` albo `(None, status)`. Statusy:
    `skipped:raw` (plan R4) · `skipped:kind_<rodzaj>` (wyłącznie `light`, plan MT-Q3; brak
    `IMAGETYP` = `kind_unknown`, nie zgadujemy) · `skipped:no_date` (bez `DATE-OBS` nie ma
    sekwencji ani torów) · `error:parse` · `error:no_image` (XISF bez `<Image>`). Przejściowy błąd
    I/O (`OSError` z kodem systemu) leci do wołającego jak w `read_binned`."""
    suffix = os.path.splitext(path)[1].lower()
    if suffix in exif.RAW_SUFFIXES:
        return None, "skipped:raw"
    try:
        header = scan.read_header(path)
        if suffix in scan.XISF_SUFFIXES:
            desc = scan.xisf_image_descriptor(path)
            if desc is None:
                return None, "error:no_image"
            width, height, channels = desc["geometry"][0], desc["geometry"][1], desc["geometry"][-1]
        else:
            width, height = _to_int(header.get("NAXIS1")), _to_int(header.get("NAXIS2"))
            channels = 1
    except (OSError, ValueError) as exc:
        if _parse_failure(exc):
            return None, "error:parse"
        raise
    kind = normalize_kind(header.get("IMAGETYP"))
    if kind != "light":
        return None, f"skipped:kind_{kind}"
    time = _date_obs(header.get("DATE-OBS"))
    if time is None:
        return None, "skipped:no_date"
    exptime = _to_float(header.get("EXPTIME"))
    return FrameFacts(ref=path, time=time,
                      exptime=_to_float(header.get("EXPOSURE")) if exptime is None else exptime,
                      camera=_to_text(header.get("INSTRUME")), telescope=_to_text(header.get("TELESCOP")),
                      filter=_to_text(header.get("FILTER")), width=width, height=height,
                      binning=_to_int(header.get("XBINNING")) or 1, channels=channels,
                      rotation=_to_float(header.get("OBJCTROT"))), None


@dataclass(frozen=True)
class FolderFrame:
    """Klatka trybu katalogu: plik, status i miejsce w sekwencji (`seq`, `index`) - None dla
    klatki, która do sekwencji nie weszła (status z `folder_facts`)."""
    path: str
    status: str
    facts: FrameFacts = None
    seq: int = None
    index: int = None
    result: FrameResult = None


@dataclass(frozen=True)
class FolderStreak:
    """Ślad trybu katalogu z torem i propozycją klasy. `k` = numer śladu w klatce; `track` = numer
    toru w przebiegu albo None; `crop` = wycinek RGB (`render_crop`)."""
    frame: FolderFrame
    k: int
    streak: Streak
    track: int
    ambiguous: bool
    cls: str
    crop: object


@dataclass(frozen=True)
class FolderScan:
    """Wynik `scan_folder`. `frames` w kolejności wejść, `streaks` w kolejności (sekwencja, klatka,
    ślad), `sequences` = krotki `FrameFacts` każdej sekwencji. `inputs_sha1` = sha1 posortowanej
    listy `ścieżka względna, mtime_ns, rozmiar` (manifest, plan §2 Z2)."""
    folder: str
    frames: tuple
    streaks: tuple
    sequences: tuple
    tracks: int
    unread_dirs: tuple
    inputs_sha1: str
    params: dict


# PRZEJŚCIOWY BŁĄD I/O W TRYBIE KATALOGU = STATUS `error:io` KLATKI, nie przerwanie przebiegu.
# Rdzeń (`read_binned`, `folder_facts`) przepuszcza `OSError` z kodem systemu, bo w trybie bazy
# status byłby TRWAŁĄ etykietą zdrowej klatki, a wołający ponawia. Raport katalogu jest jednorazowy
# i niczego nie utrwala: nieczytelny sub (ACL, zerwany SMB, plik zniknął po wylistowaniu) dostaje
# w `frames.csv` status `error:io` jak inne `error:*` z planu, przestaje być sąsiadem, a reszta nocy
# liczy się dalej - kwadrans przebiegu nie pada przez jeden plik. Zerwany cały udział daje
# `error:io` na wszystkich dalszych klatkach - widoczne w statusach podsumowania, nie ukryte.

def _stat_or_none(path):
    try:
        return os.stat(path)
    except OSError:
        return None


def _facts_or_io_error(path):
    try:
        return folder_facts(path)
    except OSError:
        return None, "error:io"


def _read_or_io_error(path, bin):
    try:
        return read_binned(path, bin)
    except OSError:
        return Binned("error:io", bin=bin)


def scan_folder(folder, paths, *, k_sigma=K_SIGMA, min_len_native=MIN_LEN_NATIVE, bin=BIN, workers=1,
                unread_dirs=(), progress=None):
    """Tryb katalogu bez bazy: fakty z nagłówków `paths` (wynik `folder_inputs`), sekwencje,
    detekcja z wycinkami, tory i klasy. Odczyt wyłącznie - zapis raportu robi wołający
    (`report_files` + drzwi `horreum/raport.py`).

    Równoległość: nagłówki i porcje sekwencji (`CHUNK_MIN`-`CHUNK_MAX` klatek) na `workers`
    wątkach; numpy zwalnia GIL w medianie, FFT i odczycie. Porcja czyta przy brzegu do 2n klatek
    sąsiedniej porcji drugi raz - zbiór sąsiadów klatki zależy od sekwencji, nie od porcji, więc
    wynik nie zależy od `workers`. `progress(gotowe, wszystkie)` po każdej porcji (klatki)."""
    if workers < 1:
        raise ValueError(f"workers={workers} - musi być >= 1")
    with ThreadPoolExecutor(workers) as ex:
        stats = list(ex.map(_stat_or_none, paths))
        facts = list(ex.map(_facts_or_io_error, paths))
    stamps = sorted(f"{os.path.relpath(p, folder)}\t{st.st_mtime_ns}\t{st.st_size}"
                    if st else f"{os.path.relpath(p, folder)}\terror:io"
                    for p, st in zip(paths, stats))
    seqs = sequences([f for f, _ in facts if f is not None])
    jobs = []
    for si, seq in enumerate(seqs):
        size = min(CHUNK_MAX, max(CHUNK_MIN, math.ceil(len(seq) / workers)))
        jobs += [(si, lo, min(len(seq), lo + size)) for lo in range(0, len(seq), size)]

    def run(job):
        si, lo, hi = job
        seq = seqs[si]
        return job, list(scan_sequence(len(seq), lambda j: _read_or_io_error(seq[j].ref, bin), start=lo,
                                       stop=hi, k_sigma=k_sigma, min_len_native=min_len_native,
                                       bin=bin, crops=True))

    results, done, total = {}, 0, sum(len(s) for s in seqs)
    with ThreadPoolExecutor(workers) as ex:
        for (si, lo, hi), part in ex.map(run, jobs):
            results.update(((si, fr.index), fr) for fr in part)
            done += hi - lo
            if progress:
                progress(done, total)

    where = {f.ref: (si, i) for si, seq in enumerate(seqs) for i, f in enumerate(seq)}
    frames, row_of = [], {}
    for path, (f, status) in zip(paths, facts):
        if f is None:
            frames.append(FolderFrame(path, status))
            continue
        si, i = where[path]
        fr = results[(si, i)]
        row_of[(si, i)] = FolderFrame(path, fr.status, f, si, i, fr)
        frames.append(row_of[(si, i)])

    out, n_tracks = [], 0
    for si, seq in enumerate(seqs):
        items, owners = [], []
        for i, f in enumerate(seq):
            for k, s in enumerate(results[(si, i)].streaks):
                items.append((i, (f.time - seq[0].time).total_seconds(), s))
                owners.append((i, k))
        linked = link_tracks(items, cadence([f.time for f in seq]), bin)
        track_of = {}
        for chain in linked.tracks:
            track_of.update((k, (n_tracks, len(chain))) for k in chain)
            n_tracks += 1
        parallel = {i: parallel_partners(results[(si, i)].streaks) for i, _ in owners}
        for idx, (i, k) in enumerate(owners):
            fr = results[(si, i)]
            track, track_len = track_of.get(idx, (None, 1))
            out.append(FolderStreak(row_of[(si, i)], k, fr.streaks[k], track, idx in linked.ambiguous,
                                    classify(fr.streaks[k], track_len=track_len, parallel=k in parallel[i]),
                                    fr.crops[k] if fr.crops else None))
    return FolderScan(folder=folder, frames=tuple(frames), streaks=tuple(out),
                      sequences=tuple(tuple(s) for s in seqs), tracks=n_tracks,
                      unread_dirs=tuple(unread_dirs),
                      inputs_sha1=hashlib.sha1("\n".join(stamps).encode("utf-8")).hexdigest(),
                      params={"k_sigma": k_sigma, "min_len_native": min_len_native, "bin": bin,
                              "workers": workers})


def _num(value, nd=2):
    return "" if value is None else (f"{value:.{nd}f}" if isinstance(value, float) else str(value))


def _csv(header, rows):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    w.writerows(rows)
    return buf.getvalue().encode("utf-8")


def _crop_name(s):
    return f"crops/s{s.frame.seq:03d}_f{s.frame.index:04d}_{s.k}.png"


_CLASS_ORDER = {"meteor?": 0, "nieokreslony": 1, "samolot": 2, "satelita": 3}


def summary(res):
    """Podsumowanie przebiegu (słownik pod `summary.json` i wydruk CLI): statusy klatek, sekwencje,
    `hough_segments` / `streaks` / `tracks` osobno (plan §2), klasy, kandydaci meteoru. Jasność
    graniczna (`Q0-d`) wymaga punktu zerowego z ASTAP + Gaia - tryb katalogu jej nie liczy i mówi
    to wprost, żeby brak śladów nie czytał się jak „nie było meteorów"."""
    classes = Counter(s.cls for s in res.streaks)
    return {
        "folder": res.folder,
        "files": len(res.frames),
        "unread_dirs": list(res.unread_dirs),
        "statuses": dict(sorted(Counter(f.status for f in res.frames).items())),
        "sequences": [{"seq": si, "frames": len(seq), "first": seq[0].time.isoformat(),
                       "last": seq[-1].time.isoformat(), "exptime": seq[0].exptime,
                       "filter": seq[0].filter, "camera": seq[0].camera,
                       "telescope": seq[0].telescope, "cadence_s": cadence([f.time for f in seq])}
                      for si, seq in enumerate(res.sequences)],
        "hough_segments": sum(f.result.hough_segments for f in res.frames if f.result),
        "streaks": len(res.streaks),
        "tracks": res.tracks,
        "ambiguous": sum(s.ambiguous for s in res.streaks),
        "classes": dict(sorted(classes.items())),
        "meteor_candidates": sum(n for c, n in classes.items() if c.startswith("meteor")),
        "radiant_test": None,
        "radiant_note": "brak WCS - test radiantu nie wykonany (decyzja Q0-c: WCS wyłącznie "
                        "z rozwiązania zewnętrznego); klasa meteor:<rój> nie jest nadawana",
        "limiting_mag": None,
        "limiting_mag_note": "nie liczona w trybie katalogu (wymaga punktu zerowego ASTAP + Gaia, "
                             "decyzja Q0-d); brak kandydatów nie znaczy braku meteorów",
        "mosaic_tiles": min(len(res.streaks), MOSAIC_MAX),
    }


def manifest(res, *, started, finished):
    """Manifest przebiegu (plan §2 Z2): parametry, tożsamość wejść i kodu, wersje bibliotek
    i assetu rojów. Dwa przebiegi z tym samym manifestem dają ten sam zbiór śladów."""
    import astropy

    from . import __version__
    with open(__file__, "rb") as fh:
        code = hashlib.sha1(fh.read()).hexdigest()
    showers = resources.files("horreum.data").joinpath("meteor_showers.json").read_bytes()
    return {
        "tool": "horreum streaks --folder",
        "horreum": __version__,
        "folder": res.folder,
        "k_sigma": res.params["k_sigma"],
        "min_len_native": res.params["min_len_native"],
        "bin": res.params["bin"],
        "n_neighbours": N_NEIGHBOURS,
        "align": "integer",
        "limit": None,
        "n_files": len(res.frames),
        "inputs_sha1": res.inputs_sha1,
        "streaks_sha1": code,
        "showers_sha1": hashlib.sha1(showers).hexdigest(),
        "showers_built": json.loads(showers)["_meta"]["built"],
        "numpy": np.__version__,
        "astropy": astropy.__version__,
        "wcs": None,
        "wcs_parity": None,
        "workers": res.params["workers"],
        "started": started,
        "finished": finished,
    }


def report_files(res, *, started, finished):
    """Raport jako lista `(nazwa względna, bajty)` w kolejności zapisu: `frames.csv`, `streaks.csv`,
    `crops/*.png`, `mosaic.png` (gdy są ślady), `summary.json`, `manifest.json` NA KOŃCU - manifest
    w katalogu znaczy „raport kompletny". Współrzędne w CSV w pikselach NATYWNYCH (plan §0)."""
    rel = {f.path: os.path.relpath(f.path, res.folder) for f in res.frames}
    files = [("frames.csv", _csv(
        ["file", "status", "seq", "frame", "date_obs", "exptime", "filter", "camera", "telescope",
         "sigma", "margin", "n_neighbours", "hough_segments", "streaks"],
        [[rel[f.path], f.status, _num(f.seq), _num(f.index),
          f.facts.time.isoformat() if f.facts else "", _num(f.facts.exptime if f.facts else None),
          (f.facts.filter or "") if f.facts else "", (f.facts.camera or "") if f.facts else "",
          (f.facts.telescope or "") if f.facts else "",
          _num(f.result.sigma if f.result else None, 3), _num(f.result.margin if f.result else None),
          _num(f.result.n_neighbours if f.result else None),
          _num(f.result.hough_segments if f.result else None),
          _num(len(f.result.streaks) if f.result else None)] for f in res.frames]))]
    files.append(("streaks.csv", _csv(
        ["seq", "frame", "file", "date_obs", "exptime", "filter", "k", "x0", "y0", "x1", "y1", "theta",
         "length", "width", "snr", "cv", "end0", "end1", "edge_ends", "masked_frac", "blink_fap",
         "blink_period", "track", "ambiguous", "class", "crop"],
        [[s.frame.seq, s.frame.index, rel[s.frame.path], s.frame.facts.time.isoformat(),
          _num(s.frame.facts.exptime), s.frame.facts.filter or "", s.k,
          _num(s.streak.x0), _num(s.streak.y0), _num(s.streak.x1), _num(s.streak.y1),
          _num(s.streak.theta), _num(float(s.streak.length), 1), _num(s.streak.width),
          _num(s.streak.snr), _num(s.streak.cv, 3), _num(s.streak.end0, 3), _num(s.streak.end1, 3),
          s.streak.edge_ends, _num(s.streak.masked_frac, 3),
          "" if s.streak.blink_fap is None else f"{s.streak.blink_fap:.3g}", _num(s.streak.blink_period, 1),
          _num(s.track), int(s.ambiguous), s.cls, _crop_name(s) if s.crop is not None else ""]
         for s in res.streaks])))
    files += [(_crop_name(s), png_bytes(s.crop)) for s in res.streaks if s.crop is not None]
    shown = sorted((s for s in res.streaks if s.crop is not None),
                   key=lambda s: (_CLASS_ORDER.get(s.cls, -1), s.frame.seq, s.frame.index, s.k))
    tiles = mosaic([s.crop for s in shown[:MOSAIC_MAX]])
    if tiles is not None:
        files.append(("mosaic.png", png_bytes(tiles)))
    files.append(("summary.json", json.dumps(summary(res), ensure_ascii=False, indent=1).encode("utf-8")))
    files.append(("manifest.json", json.dumps(manifest(res, started=started, finished=finished),
                                              ensure_ascii=False, indent=1).encode("utf-8")))
    return files
