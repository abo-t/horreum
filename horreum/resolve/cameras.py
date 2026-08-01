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

# Rodzaje, które NIE zeznają o rozmiarze piksela MATRYCY — decyzja Zdzinia 2026-08-02 (I-2b):
# „oś podziału masterów na piksele jest mi niepotrzebna, ważne jaką kamerą robione".
#
# Bliźniak `grouper.NO_TELESCOPE_KINDS` i `resolver.NO_OBJECT_CARD_FILETYPES` — ta sama figura:
# populacja, która pewnego faktu NIE MA Z DEFINICJI, wypada z JEGO osi, a nie z osi w ogóle.
# Gotowy obraz po integracji nadal powołuje KAMERĘ (to samo `model_canon`), bo „czym robione"
# jest pytaniem sensownym; przestaje tylko wnosić `XPIXSZ`.
#
# DLACZEGO — zmierzone na 128 realnych stosach, dwie różne przyczyny tego samego objawu:
#   * `_drizzle_2x` zapisuje `XPIXSZ=1.88` przy matrycy 3.76. To NIE jest błąd danych: drizzle
#     zagęszcza siatkę, więc produkt uczciwie opisuje piksel WYNIKOWY. Tożsamość kamery opisuje
#     jednak sprzęt, a nie siatkę wyjściową — mieszanie ich rozbiłoby jedną kamerę na dwie.
#   * korpusy Sony podają w produkcie integracji `5.4` tam, gdzie archiwum zna `4.86` (ILCE-7RM3A),
#     i tam, gdzie nie zna nic (ILCE-7S — EXIF piksela nie podaje). Ta wartość jest WĄTPLIWA
#     i nie ma prawa nadpisać ani podważyć zeznania klatek z akwizycji.
# Bez tej bramki oba przypadki zapalały `camera.pixel_conflict` na osi (zmierzone: 2 kamery).
NO_PIXEL_KINDS = frozenset({"master_light"})


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
    # Sony: PixInsight zapisuje kod modelu 'Sony ILCE-7RM3A', akwizycja FITS 'Sony A7RM3' — ten sam
    # korpus alfa 7R III (firsthand PF-4: 1 masterflat XISF rozbijal kamere na 6. tozsamosc). Fold
    # ILCE-7RM3[A] -> A7RM3, by jedna kamera fizyczna miala jedna tozsamosc (decyzja Zdzisawa PF-4;
    # brief §3 „normalize_camera 1:1" rozszerzony o forme ILCE). Idempotentne: 'A7RM3' nie nosi ILCE.
    s = re.sub(r"\bILCE-?7RM3A?\b", "A7RM3", s)
    # DSLR/RAW (#2, D-R-5): pozostałe korpusy Sony alfa 7 do formy 'A7…' — paralela do foldu 7RM3A,
    # jedna kamera fizyczna = jedna tożsamość na osi. 7RM3 zdjęte wyżej, więc te wzorce się nie
    # przecinają (po '7' idzie 'S'/'M3', nie 'RM3'). Idempotentne: 'A7S'/'A7M3' nie noszą ILCE.
    s = re.sub(r"\bILCE-?7M3\b", "A7M3", s)
    s = re.sub(r"\bILCE-?7S\b", "A7S", s)
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
    pixel_um: object             # float | None — WŁAŚCIWOŚĆ, nie klucz (brief §3/R1#3)
    is_mono: object              # 1 mono | 0 kolor | None (review)
    is_mono_source: str
    raw_instrume: object         # surowy INSTRUME (audyt) | None


def camera_identity(header, *, raw_format=None, kind=None):
    """Wyłoń tożsamość kamery ze zeznania nagłówka (dict ze skanu). Brief przejścia §3.

    `raw_format` (#2, D-R-2/znal.2): FAKT formatu pliku (RAW/DSLR), NIE karta nagłówka — wołający
    (`scan.ingest_record`) podaje go z rozszerzenia, bo zeznanie EXIF nie niesie BAYERPAT, a DSLR
    to zawsze kolor (mozaika w formacie). Aktywuje gałąź `is_mono(raw_format=…)`; FITS/XISF podają
    None → zachowanie bez zmian. NIE przemycamy markera do dict-a (byłaby to fabrykacja karty).

    `kind` (I-2b, decyzja Zdzinia 2026-08-02): rodzaj klatki — TEŻ fakt spoza nagłówka w sensie osi
    (wyprowadza go `scan._derive_kind`). Służy WYŁĄCZNIE bramce `NO_PIXEL_KINDS`: rodzaj, który nie
    zeznaje o pikselu matrycy, oddaje `pixel_um=None` mimo obecnej karty `XPIXSZ`. Model wraca
    normalnie — kamera zostaje wyłoniona, bo „czym robione" pozostaje pytaniem sensownym.
    `None` (domyślnie) = zachowanie bez zmian; karta rządzi.

    KONTRAKT ODWRÓCONY (R1#3/R2#4): tożsamość wymaga TYLKO `model_canon` — po naprawie nagłówków
    INSTRUME jest w 100% klatek, a model rozstrzyga oś. `pixel_um` to Optional WŁAŚCIWOŚĆ
    (brak XPIXSZ — np. Sony masterflat — NIE blokuje osi; uzupełni ją `repo.upsert_camera`,
    rozjazd wartości = stan `pixel_conflict`). None WYŁĄCZNIE przy braku INSTRUME — wtedy review
    należy do warstwy frame (§4.2): `event(camera.review)`.

    W3: XPIXSZ rzutowany na float (`_to_float`) — XISF podaje liczby jako STRINGI; właściwość
    musi mieć typ jednolity (inaczej CAS w upsert_camera widziałby fałszywy rozjazd
    `'3.76'` vs `3.76`). `raw_json` (gdzie indziej) zostaje 1:1 surowy.

    Reguła B (OSC): ZWO bez sufiksu (`^ASI\\d+$`) z kolorem potwierdzonym BAYERPAT (is_mono=0)
    → domknięcie na MC (`ASI294`→`ASI294MC`). NIGDY MM/MD — brak BAYERPAT zostaje review (nie
    zgadujemy). Idempotentne: `ASI294MC` ma sufiks nie-cyfrowy → regex nie łapie → nietykane.
    AGNOSTYCZNA (§5.8): ASI294 bez BAYERPAT → oś powstaje, mono=review; nie-ZWO (Sony placeholder)
    Reguła B nie tyka (regex ZWO-only); jego mapowanie na body ILCE = drugi przebieg (RAW).
    """
    raw_instrume = header.get("INSTRUME")
    model_canon = normalize_camera(raw_instrume)
    # Bramka PRZED rzutem, nie po: dla `NO_PIXEL_KINDS` karta `XPIXSZ` w ogóle nie wchodzi na oś
    # (nie „wchodzi i jest ignorowana"), więc `upsert_camera` nie ma czego uzupełnić ani z czym
    # skonfliktować — a zeznanie pliku zostaje nietknięte w `header`/`cards` do audytu.
    pixel_um = (None if kind in NO_PIXEL_KINDS
                else _to_float(header.get("XPIXSZ")))   # W3: XISF zwraca string → rzut na float
    if not model_canon:
        return None
    mono, source = is_mono(bayerpat=header.get("BAYERPAT"), model_canon=model_canon,
                           raw_format=raw_format)
    if mono == 0 and re.fullmatch(r"ASI\d+", model_canon):   # Reguła B: OSC ZWO + kolor → MC
        model_canon += "MC"
    return CameraIdentity(
        model_canon=model_canon, pixel_um=pixel_um,
        is_mono=mono, is_mono_source=source, raw_instrume=raw_instrume,
    )
