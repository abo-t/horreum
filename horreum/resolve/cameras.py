"""Oś KAMERA — tożsamość = (model_canon, pixel_um) (PLAN §3.1).

`normalize_camera` przeniesione 1:1 z `custos/resolve/rigs.py` (zamrożony Custos). JEDYNE
źródło tożsamości kamery (inwariant A1) — `match_rig` (rig z folderu) świadomie NIE przeniesiony
(nieprzenośny; Horreum bierze teleskop z sygnatury nagłówka, nie ze ścieżki).

`GAIN/OFFSET/CCD-TEMP/USBLIMIT` to USTAWIENIA akwizycji → `header` (audyt), NIGDY tożsamość.
"""
import re
from dataclasses import dataclass

from ._coerce import _to_float
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


@dataclass(frozen=True)
class CameraIdentity:
    """Oś KAMERA wyłuskana ze zeznania nagłówka — wejście dla `repo.upsert_camera` (te same pola).
    Czysta dana, NIE zapis: sam upsert (jedna klinga + event) należy do repo."""
    model_canon: str
    pixel_um: float
    is_mono: object              # 1 mono | 0 kolor | None (review)
    is_mono_source: str
    raw_instrume: object         # surowy INSTRUME (audyt) | None


def camera_identity(header):
    """Wyłoń tożsamość kamery ze zeznania nagłówka (dict ze skanu). PLAN §3.1/§3.6/§Etap 2.

    Zwraca `CameraIdentity` albo None, gdy tożsamości NIE da się złożyć — brak INSTRUME do
    normalizacji LUB brak/niefloat XPIXSZ (a `pixel_um` jest częścią klucza UNIQUE, NOT NULL).
    Wtedy review należy do warstwy frame (§4.2): `event(camera.review)` przy braku osi.

    W3: XPIXSZ rzutowany na float (`_to_float`) — XISF podaje liczby jako STRINGI, niejednolity
    typ rozbiłby `UNIQUE(model_canon, pixel_um)` na FITS-float vs XISF-string. `raw_json` (gdzie
    indziej) zostaje 1:1 surowy; tu pole gorące = typ jednolity.

    Reguła B (OSC): ZWO bez sufiksu (`^ASI\\d+$`) z kolorem potwierdzonym BAYERPAT (is_mono=0)
    → domknięcie na MC (`ASI294`→`ASI294MC`). NIGDY MM/MD — brak BAYERPAT zostaje review (nie
    zgadujemy). Idempotentne: `ASI294MC` ma sufiks nie-cyfrowy → regex nie łapie → nietykane.
    AGNOSTYCZNA (§5.8): ASI294 bez BAYERPAT → oś powstaje, mono=review; nie-ZWO (Sony placeholder)
    Reguła B nie tyka (regex ZWO-only); jego mapowanie na body ILCE = drugi przebieg (RAW).
    """
    raw_instrume = header.get("INSTRUME")
    model_canon = normalize_camera(raw_instrume)
    pixel_um = _to_float(header.get("XPIXSZ"))   # W3: XISF zwraca string → rzut na float
    if not model_canon or pixel_um is None:
        return None
    mono, source = is_mono(bayerpat=header.get("BAYERPAT"), model_canon=model_canon)
    if mono == 0 and re.fullmatch(r"ASI\d+", model_canon):   # Reguła B: OSC ZWO + kolor → MC
        model_canon += "MC"
    return CameraIdentity(
        model_canon=model_canon, pixel_um=pixel_um,
        is_mono=mono, is_mono_source=source, raw_instrume=raw_instrume,
    )
