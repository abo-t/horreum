"""Wyłuskanie pól gorących z nagłówka — zeznanie → kolumny `header` (W2/W3, PLAN §3.3/§3.5/§Etap 4).

`raw_json` (gdzie indziej) zostaje 1:1 surowy; TU rzutujemy pola gorące na typy kolumn `header`.
XISF zwraca wartości jako STRINGI — bez rzutu oś TELESKOPU rozbiłaby się FITS-vs-XISF tak samo,
jak groziło kamerom (W3). Czysta funkcja (zero zapisu). Klucze zwracanego dict = nazwy kolumn
`header` → wejście dla `repo.record_header(**fields)`.

Świadomie POMIJANE tutaj: `focratio_norm`/`focratio_norm_src` (backfill grouper, §Etap 5)
— `record_header` domyśla je NULL.
"""
from ._coerce import _to_float, _to_int, _to_text


def extract_header(header):
    """Nagłówek (dict ze skanu) → dict pól gorących (klucze = kolumny `header`). Pułapki (W2/W3):
    FILTER nieobecny/pusty `''` → `filter_raw=None`; `GAIN`/`OFFSET=0` to wartość, nie None;
    wszystkie pola liczbowe przez `_to_float`/`_to_int` (XISF-string → typ jednolity, W3);
    `gain` jako TEXT „spójnie" (audyt). `OFFSET`→`offset_adu` ('offset' = słowo zarezerwowane)."""
    g = header.get
    return {
        "date_obs": _to_text(g("DATE-OBS")),
        "exptime": _to_float(g("EXPTIME")),
        "filter_raw": _to_text(g("FILTER")),       # pusty '' → None (W2)
        "instrume": _to_text(g("INSTRUME")),
        "telescop": _to_text(g("TELESCOP")),       # surowy (brudny) — grouper §Etap 5
        "focallen": _to_float(g("FOCALLEN")),
        "focratio_raw": _to_float(g("FOCRATIO")),
        "xpixsz": _to_float(g("XPIXSZ")),
        "ypixsz": _to_float(g("YPIXSZ")),          # sanity: == xpixsz (kryterium, nie tożsamość)
        "gain": _to_text(g("GAIN")),               # TEXT audyt „spójnie" (0 → '0', nie None)
        "offset_adu": _to_int(g("OFFSET")),
        "ccd_temp": _to_float(g("CCD-TEMP")),
        "usblimit": _to_int(g("USBLIMIT")),
        "xbinning": _to_int(g("XBINNING")),
        "ybinning": _to_int(g("YBINNING")),
        "bayerpat": _to_text(g("BAYERPAT")),
        "ra_deg": _to_float(g("RA")),              # stopnie dziesiętne (RA, nie sexagesimal OBJCTRA)
        "dec_deg": _to_float(g("DEC")),            # stopnie dziesiętne (DEC, nie OBJCTDEC); 0 = wartość
        "object_raw": _to_text(g("OBJECT")),       # "plotka" — resolver obiektu §Etap 6
    }


# ZEZNANIE KOPII (migracja 0021): kolumna `location` → keyword nagłówka, w kolejności pokazywania.
# Jedno źródło dla zapisu (`copy_testimony`) i dla powierzchni, która nazywa rozbieżne pole
# nazwą z pliku (`FILTER`, nie `hdr_filter`) - nazwa keyworda jest faktem domenowym, nie etykietą UI.
# Dobór pól i powód („karmią oś klatki albo wybór po wartości") - w nagłówku migracji 0021.
COPY_TESTIMONY_KEYWORDS = (
    ("hdr_filter", "FILTER"), ("hdr_imagetyp", "IMAGETYP"), ("hdr_object", "OBJECT"),
    ("hdr_telescop", "TELESCOP"), ("hdr_instrume", "INSTRUME"), ("hdr_exptime", "EXPTIME"),
    ("hdr_xbinning", "XBINNING"), ("hdr_date_obs", "DATE-OBS"),
)


def copy_testimony(header):
    """Nagłówek JEDNEJ KOPII (dict ze skanu) → dict pól `hdr_*` na `location` (0021).

    Koercja NIE jest tu pisana drugi raz: siedem z ośmiu pól bierzemy z `extract_header`, czyli z TEJ
    SAMEJ derywacji, która karmi `header` klatki - inaczej zeznanie kopii i zeznanie klatki mogłyby
    różnić się samym rzutem (XISF-owy tekst `'1.34'` obok FITS-owego `1.34`) i porównanie kopii
    widziałoby rozjazd, którego w plikach nie ma. `IMAGETYP` nie jest polem gorącym `header` (rodzaj
    klatki liczy `normalize_kind`), więc dostaje ten sam rzut tekstowy, co pozostałe pola tekstowe."""
    hot = extract_header(header)
    return {
        "hdr_filter": hot["filter_raw"],
        "hdr_imagetyp": _to_text(header.get("IMAGETYP")),
        "hdr_object": hot["object_raw"],
        "hdr_telescop": hot["telescop"],
        "hdr_instrume": hot["instrume"],
        "hdr_exptime": hot["exptime"],
        "hdr_xbinning": hot["xbinning"],
        "hdr_date_obs": hot["date_obs"],
    }
