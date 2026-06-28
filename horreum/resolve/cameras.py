"""Oś KAMERA — tożsamość = (model_canon, pixel_um) (PLAN §3.1).

`normalize_camera` przeniesione 1:1 z `custos/resolve/rigs.py` (zamrożony Custos). JEDYNE
źródło tożsamości kamery (inwariant A1) — `match_rig` (rig z folderu) świadomie NIE przeniesiony
(nieprzenośny; Horreum bierze teleskop z sygnatury nagłówka, nie ze ścieżki).

`GAIN/OFFSET/CCD-TEMP/USBLIMIT` to USTAWIENIA akwizycji → `header` (audyt), NIGDY tożsamość.
"""
import re

from ._text import norm


def normalize_camera(instrume):
    """Znormalizuj kamerę: 'ZWO ASI2600MM Pro' -> 'ASI2600MM'. None gdy brak.

    Body 'Duo' niesie sensor MM, ale to OSOBNA kamera (inna optyka kalibracyjna) -> 'ASI2600MD'
    (detekcja po tokenie 'Duo'). To rozjazd, który w Custosie rozbił Pro/Duo — tu jest FAKTEM,
    nie regexem nazwy. Idempotentne: normalize_camera(normalize_camera(x)) == normalize_camera(x)
    (MD w alternacji łapie już-znormalizowaną formę; żaden surowy INSTRUME nie nosi 'MD')."""
    if not instrume:
        return None
    s = norm(instrume)
    m = re.search(r"ASI\s?0*(\d{3,4})\s?(MM|MC|MD)?", s)
    if m:
        suffix = m.group(2) or ""
        if suffix == "MM" and re.search(r"\bDUO\b", s):
            suffix = "MD"                       # sensor MM, body Duo = osobna kamera
        return f"ASI{m.group(1)}{suffix}"
    cleaned = re.sub(r"\b(ZWO|PRO|CAMERA|CMOS|CCD)\b", "", s)
    cleaned = re.sub(r"[^A-Z0-9]+", "", cleaned)
    return cleaned or None


def is_mono(*, bayerpat=None, model_canon=None, raw_format=None):
    """mono/kolor — reguła JEDNOKIERUNKOWA (PLAN §3.2, zwalidowana firsthand: 0 anomalii).

    Zwraca (is_mono, source): is_mono ∈ {1 mono, 0 kolor, None review}. Priorytet źródeł:
      1. BAYERPAT obecny ⟹ kolor (OSC), 100% pewne                      -> 'bayerpat'
      2. brak BAYERPAT + model ZWO (MM/MD=mono, MC=kolor)               -> 'model'
      3. format raw/DNG (DSLR) ⟹ kolor (mozaika w formacie, nie w nagłówku) -> 'raw_format'
      4. nierozstrzygalne                                               -> 'review'

    UWAGA: brak BAYERPAT NIE znaczy mono — MM-mono (ZWO) i kolor-DSLR (Sony bez BAYERPAT)
    wyglądają identycznie. Dlatego Sony-w-FITS bez modelu ZWO i bez raw_format → review (F10).
    """
    if bayerpat:                                # obecny (niepusty) => kolor
        return 0, "bayerpat"
    if model_canon:
        if model_canon.endswith("MC"):
            return 0, "model"
        if model_canon.endswith(("MM", "MD")):
            return 1, "model"
    if raw_format:                              # DSLR raw bez BAYERPAT => kolor
        return 0, "raw_format"
    return None, "review"
