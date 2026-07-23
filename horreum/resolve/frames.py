"""Oś rodzaju klatki — `normalize_kind(imagetyp)` → kanon `kind` (PLAN §1.4/§Etap 3).

`kind` koduje OBA wymiary w jednym polu: sub vs master ORAZ rodzaj —
`light | flat | dark | bias | master_flat | master_dark | master_light | unknown`
(„wszystkie mastery" = `WHERE kind LIKE 'master_%'`). Czysta funkcja mapująca; sam zapis (z
`event(kind.unmapped)` dla NIEPUSTEGO-niezmapowanego IMAGETYP) należy do warstwy frame (§Etap 4),
nie tu.

Mapa = WYŁĄCZNIE zeznanie firsthand + warianty „na zapas" (agnostyczność §5.8): NIE zgaduje —
nierozpoznane/brak → `unknown` jawnie (sygnał do rozszerzenia mapy, nie ciche dopasowanie).
"""
import re
from pathlib import Path

# DSLR/RAW (#2, D-R-4): rodzaj klatki z NAZWY KATALOGU (case-insensitive, dokładny segment).
# Wąska mapa — tylko cztery rodzaje sub-klatek, jakie może nieść drzewo akwizycji.
_KIND_DIRS = {
    "light": "light", "lights": "light",
    "dark": "dark", "darks": "dark",
    "flat": "flat", "flats": "flat",
    "bias": "bias", "biases": "bias",
}

# Po normalizacji (lower, kolaps białych znaków/`_`, zdjęcie końcowego „ frame") → kanon kind.
_KIND_MAP = {
    "light": "light",                # FITS: LIGHT/Light/Light Frame · XISF: LIGHT
    "flat": "flat",                  # FITS: FLAT · XISF: FLAT
    "dark": "dark",                  # „na zapas" — w archiwum 2600 nieobecne
    "bias": "bias",                  # „na zapas"
    "master flat": "master_flat",    # XISF: Master Flat
    "master dark": "master_dark",    # XISF: Master Dark
    "master light": "master_light",  # „na zapas"
    "integration": "master_light",   # PixInsight: zintegrowany stack = master light
}


def normalize_kind(imagetyp):
    """IMAGETYP (FITS/XISF) → kanon `kind`. Case-insensitive, kolaps białych znaków i `_`,
    zdjęcie końcowego „ frame" (`Light Frame`→light, `Dark Frame`→dark). Brak/nierozpoznane →
    `unknown` (jawne — NIE zgadujemy; niepuste-niezmapowane sygnalizuje warstwa zapisu, §Etap 4)."""
    if not imagetyp:
        return "unknown"
    key = re.sub(r"[\s_]+", " ", str(imagetyp).strip().lower())
    key = re.sub(r" frame$", "", key)          # zdejmij sufiks „ frame" (Light Frame → light)
    return _KIND_MAP.get(key, "unknown")


def kind_from_path(path):
    """Rodzaj klatki z FOLDERU — RAW nie niesie IMAGETYP w EXIF (#2, D-R-4; `kind_source='path'`).
    Precedens C1: ścieżka jako źródło faktu (wąski, jawny, dowodowy). Dopasowanie po SEGMENCIE
    (dokładna nazwa katalogu, case-insensitive) — NIE substring: folder obiektu „IC1318" nie ma
    nic udawać. Żaden pasujący segment → 'unknown' (NIE zgadujemy; DSLR-kalibracja = dług na przyszłość,
    dziś 763 RAW pod katalogiem LIGHTS). Pierwszy pasujący segment od korzenia wygrywa."""
    for seg in Path(path).parts:
        k = _KIND_DIRS.get(seg.strip().lower())
        if k:
            return k
    return "unknown"
