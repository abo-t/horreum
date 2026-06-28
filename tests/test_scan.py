"""Skan drzewa FITS — primitivy read-only (PLAN §4 krok 1): sha1 + nagłówek + stat.

Buduje REALNE pliki FITS przez astropy (pierwsza zależność runtime) i czyta je z powrotem.
"""
import hashlib
import json

import numpy as np
import pytest
from astropy.io import fits

from horreum.scan import iter_fits, read_fits_header, scan_file


def _write_fits(path, cards=(), data=None, extra_hdus=()):
    """Zapisz minimalny FITS z podanymi kartami nagłówka. `cards` = iterable (klucz, wartość)."""
    hdu = fits.PrimaryHDU(data=data)
    for kw, val in cards:
        hdu.header[kw] = val
    hdus = fits.HDUList([hdu, *extra_hdus])
    hdus.writeto(str(path))
    return path


def test_scan_file_sha1_i_stat(tmp_path):
    """sha1 == hashlib na bajtach pliku; size_bytes/mtime/path wypełnione."""
    f = _write_fits(tmp_path / "light.fits",
                    cards=[("INSTRUME", "ZWO ASI2600MM Pro"), ("XPIXSZ", 3.76)],
                    data=np.zeros((4, 4), dtype=np.uint16))
    rec = scan_file(str(f))
    assert rec.sha1 == hashlib.sha1(f.read_bytes()).hexdigest()
    assert rec.size_bytes == f.stat().st_size
    assert rec.path == str(f)
    assert rec.mtime and "T" in rec.mtime          # ISO-8601


def test_naglowek_wyluskany_i_jsonowalny(tmp_path):
    """Karty gorące czytane wiernie; cały dict serializowalny do JSON (przyszły raw_json)."""
    f = _write_fits(tmp_path / "h.fits", cards=[
        ("INSTRUME", "ZWO ASI2600MM Pro"),
        ("XPIXSZ", 3.76),
        ("FOCALLEN", 784),
        ("FOCRATIO", 5.6),
        ("OBJECT", "NGC 4258"),
        ("FILTER", "Ha"),
    ])
    hdr = read_fits_header(str(f))
    assert hdr["INSTRUME"] == "ZWO ASI2600MM Pro"
    assert hdr["XPIXSZ"] == 3.76
    assert hdr["FOCALLEN"] == 784
    assert hdr["OBJECT"] == "NGC 4258"
    json.dumps(hdr)                                # nie rzuca → JSON-owalne


def test_iter_fits_rekursywnie_i_filtruje(tmp_path):
    """Zbiera .fits/.fit/.fts (case-insensitive) rekursywnie; pomija nie-FITS; posortowane."""
    (tmp_path / "sub").mkdir()
    _write_fits(tmp_path / "a.fits")
    _write_fits(tmp_path / "b.FIT")
    _write_fits(tmp_path / "sub" / "c.fts")
    (tmp_path / "notes.txt").write_text("nie fits")
    (tmp_path / "img.xisf").write_bytes(b"XISF0")   # osobny moduł, nie tu
    got = [p.name for p in iter_fits(tmp_path)]
    assert got == sorted(["a.fits", "b.FIT", "c.fts"])


def test_comment_history_zachowane_jako_lista(tmp_path):
    """Powtarzalne COMMENT/HISTORY nie gubią wierszy (zeznanie 1:1) — lądują w liście."""
    hdu = fits.PrimaryHDU()
    hdu.header["HISTORY"] = "krok 1"
    hdu.header["HISTORY"] = "krok 2"
    hdu.header.add_comment("uwaga A")
    hdu.header.add_comment("uwaga B")
    f = tmp_path / "log.fits"
    fits.HDUList([hdu]).writeto(str(f))
    hdr = read_fits_header(str(f))
    assert hdr["HISTORY"] == ["krok 1", "krok 2"]
    assert hdr["COMMENT"] == ["uwaga A", "uwaga B"]


def test_naglowek_z_skompresowanego_hdu(tmp_path):
    """Master skompresowany: primary pusty (NAXIS=0), metadane w CompImageHDU — bierzemy je."""
    primary = fits.PrimaryHDU()                     # NAXIS=0
    comp = fits.CompImageHDU(data=np.zeros((4, 4), dtype=np.float32))
    comp.header["INSTRUME"] = "ZWO ASI2600MM Pro"
    f = tmp_path / "master.fits"
    fits.HDUList([primary, comp]).writeto(str(f))
    hdr = read_fits_header(str(f))
    assert hdr["INSTRUME"] == "ZWO ASI2600MM Pro"


def test_nie_fits_podnosi_wyjatek(tmp_path):
    """Plik, który nie jest FITS → wyjątek (skan nie zgaduje; review należy do upsertu)."""
    bad = tmp_path / "broken.fits"
    bad.write_bytes(b"to nie jest naglowek FITS")
    with pytest.raises(Exception):
        read_fits_header(str(bad))


def test_scan_nie_modyfikuje_pliku(tmp_path):
    """Inwariant append-only: skan to czysty odczyt — bajty i mtime pliku bez zmian."""
    f = _write_fits(tmp_path / "ro.fits", cards=[("OBJECT", "M31")],
                    data=np.zeros((4, 4), dtype=np.uint16))
    before = f.read_bytes()
    before_mtime = f.stat().st_mtime
    scan_file(str(f))
    assert f.read_bytes() == before
    assert f.stat().st_mtime == before_mtime
