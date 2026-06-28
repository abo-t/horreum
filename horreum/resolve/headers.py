"""Wyłuskanie pól gorących z nagłówka — zeznanie → kolumny `header` (W2/W3, PLAN §3.3/§3.5/§Etap 4).

`raw_json` (gdzie indziej) zostaje 1:1 surowy; TU rzutujemy pola gorące na typy kolumn `header`.
XISF zwraca wartości jako STRINGI — bez rzutu oś TELESKOPU rozbiłaby się FITS-vs-XISF tak samo,
jak groziło kamerom (W3). Czysta funkcja (zero zapisu). Klucze zwracanego dict = nazwy kolumn
`header` → wejście dla `repo.record_header(**fields)`.

Świadomie POMIJANE tutaj: `focratio_norm`/`focratio_norm_src` (backfill grouper, §Etap 5),
`ra_deg`/`dec_deg` (poza zakresem pierwszego przebiegu) — `record_header` domyśla je NULL.
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
        "object_raw": _to_text(g("OBJECT")),       # "plotka" — resolver obiektu §Etap 6
    }
