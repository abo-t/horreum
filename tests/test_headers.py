"""Wyłuskanie pól gorących: extract_header (W2/W3, §Etap 4).
Sedno W3: XISF-string i FITS-liczba dają TĘ SAMĄ wartość kolumny (typ jednolity) — inaczej oś
teleskopu/kamery rozbiłaby się FITS-vs-XISF."""
from horreum.resolve.headers import extract_header


def test_extract_header_fits_typy_natywne():
    f = extract_header({
        "DATE-OBS": "2026-06-28T01:02:03", "EXPTIME": 300.0, "FOCALLEN": 784, "FOCRATIO": 5.6,
        "XPIXSZ": 3.76, "YPIXSZ": 3.76, "OFFSET": 50, "GAIN": 100, "XBINNING": 1,
        "INSTRUME": "ZWO ASI2600MM Pro", "TELESCOP": "TS-Optics", "FILTER": "Ha",
        "OBJECT": "NGC 4258", "BAYERPAT": "RGGB", "CCD-TEMP": -10.0,
    })
    assert f["exptime"] == 300.0 and isinstance(f["exptime"], float)
    assert f["focallen"] == 784.0 and f["focratio_raw"] == 5.6
    assert f["xpixsz"] == 3.76 and f["ypixsz"] == 3.76
    assert f["offset_adu"] == 50 and isinstance(f["offset_adu"], int)
    assert f["xbinning"] == 1
    assert f["gain"] == "100"                  # TEXT „spójnie"
    assert f["filter_raw"] == "Ha" and f["object_raw"] == "NGC 4258"
    assert f["instrume"] == "ZWO ASI2600MM Pro" and f["telescop"] == "TS-Optics"
    assert f["ccd_temp"] == -10.0 and f["date_obs"] == "2026-06-28T01:02:03"


def test_extract_header_xisf_stringi_rzutowane_W3():
    """XISF zwraca stringi — pola gorące rzutowane na typ kolumny IDENTYCZnie jak FITS-liczba."""
    f = extract_header({
        "EXPTIME": "300", "FOCALLEN": "1600", "FOCRATIO": "8.0", "XPIXSZ": "3.76",
        "OFFSET": "50", "GAIN": "100", "XBINNING": "1", "USBLIMIT": "40",
    })
    assert f["exptime"] == 300.0 and isinstance(f["exptime"], float)
    assert f["focallen"] == 1600.0 and f["focratio_raw"] == 8.0
    assert f["xpixsz"] == 3.76
    assert f["offset_adu"] == 50 and isinstance(f["offset_adu"], int)
    assert f["xbinning"] == 1 and f["usblimit"] == 40
    assert f["gain"] == "100"


def test_extract_header_xpixsz_string_i_float_identyczne_W3():
    """Ten sam XPIXSZ jako FITS-float i XISF-string → ta sama wartość kolumny (sedno W3)."""
    assert extract_header({"XPIXSZ": 3.76})["xpixsz"] == extract_header({"XPIXSZ": "3.76"})["xpixsz"]


def test_extract_header_filter_pusty_to_none_W2():
    """FILTER nieobecny LUB pusty '' → filter_raw=None (W2; mastery XISF mają FILTER='')."""
    assert extract_header({"FILTER": ""})["filter_raw"] is None
    assert extract_header({})["filter_raw"] is None
    assert extract_header({"FILTER": "L-Pro"})["filter_raw"] == "L-Pro"


def test_extract_header_gain_offset_zero_nie_none_W2():
    """GAIN=0 / OFFSET=0 to POPRAWNE wartości — rozróżniaj od None (nie `if gain:`)."""
    f = extract_header({"GAIN": 0, "OFFSET": 0})
    assert f["gain"] == "0"                     # zero to wartość, nie brak
    assert f["offset_adu"] == 0


def test_extract_header_focratio_norm_nie_tu():
    """focratio_norm/src NIE wyłuskiwane w Etapie 4 (backfill grouper §Etap 5)."""
    f = extract_header({"FOCRATIO": "6.4"})
    assert f["focratio_raw"] == 6.4
    assert "focratio_norm" not in f


def test_extract_header_radec_backfill_D2():
    """RA/DEC = stopnie dziesiętne; rzut przez _to_float (XISF-string i FITS-float jednakowo, W3).
    Bierzemy RA/DEC (decymalne), NIE sexagesimal OBJCTRA/OBJCTDEC."""
    fits = extract_header({"RA": 162.7972981695292, "DEC": 53.50774901461591})
    xisf = extract_header({"RA": "162.7972981695292", "DEC": "53.50774901461591"})
    assert fits["ra_deg"] == 162.7972981695292 and isinstance(fits["ra_deg"], float)
    assert fits["dec_deg"] == 53.50774901461591
    assert xisf["ra_deg"] == fits["ra_deg"] and xisf["dec_deg"] == fits["dec_deg"]  # W3
    # sexagesimal NIE jest źródłem — sam OBJCTRA/OBJCTDEC bez RA/DEC → None
    assert extract_header({"OBJCTRA": "10 51 11.352", "OBJCTDEC": "+53 30 27.90"})["ra_deg"] is None


def test_extract_header_radec_zero_to_wartosc_nie_none():
    """RA=0 / DEC=0 to POPRAWNA wartość (jak gain/offset) — zapisujemy zeznanie, nie None."""
    f = extract_header({"RA": "0", "DEC": "0"})
    assert f["ra_deg"] == 0.0 and f["dec_deg"] == 0.0


def test_extract_header_radec_nieobecne_to_none():
    """Brak RA/DEC w nagłówku → None (record_header domyśli NULL)."""
    f = extract_header({})
    assert f["ra_deg"] is None and f["dec_deg"] is None


def test_extract_header_smiec_numeryczny_to_none():
    """Niekonwertowalna liczba (śmieć) → None, nie crash (W3 brzeg)."""
    f = extract_header({"XPIXSZ": "n/a", "OFFSET": "brak"})
    assert f["xpixsz"] is None and f["offset_adu"] is None
