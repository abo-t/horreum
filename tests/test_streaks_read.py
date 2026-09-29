"""Odczyt pikseli detektora śladów (`streaks.read_binned`) i deskryptor obrazu XISF
(`scan.xisf_image_descriptor`) - plan meteorów §2 i §3 Q1 (Z3, Z4).

Pliki testowe powstają w `tmp_path`: FITS przez astropy, XISF składany bajt po bajcie (sygnatura +
długość + reserved + XML + wypełnienie + blok), żeby każdy atrybut `<Image>` był pod kontrolą testu."""
import struct

import numpy as np
import pytest
from astropy.io import fits

from horreum import scan, streaks

BLOCK_AT = 4096          # początek bloku danych w składanych XISF


def _xisf(path, block, geometry, sample_format, *, byte_order=None, storage=None, compression=None,
          cut_at=None):
    attrs = [f'geometry="{geometry}"', f'sampleFormat="{sample_format}"']
    if byte_order:
        attrs.append(f'byteOrder="{byte_order}"')
    if storage:
        attrs.append(f'pixelStorage="{storage}"')
    if compression:
        attrs.append(f'compression="{compression}"')
    attrs.append(f'location="attachment:{BLOCK_AT}:{len(block)}"')
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           '<xisf version="1.0" xmlns="http://www.pixinsight.com/xisf">'
           f'<Image {" ".join(attrs)}><FITSKeyword name="EXPTIME" value="3." comment=""/></Image>'
           '</xisf>').encode("utf-8")
    head = b"XISF0100" + struct.pack("<I", len(xml)) + b"\0\0\0\0" + xml
    data = head + b"\0" * (BLOCK_AT - len(head)) + block
    path.write_bytes(data[:cut_at] if cut_at else data)
    return path


def _ramp(h=40, w=60):
    """Wartości > 255 i różne w każdym pikselu - kolejność bajtów i układ kanałów są widoczne."""
    return (np.arange(h * w, dtype=np.int64).reshape(h, w) * 7 + 300).astype(np.uint16)


# ---------------------------------------------------------------- FITS

def test_fits_unsigned_bzero_32768(tmp_path):
    """uint16 zapisany jako int16 + BZERO=32768: wartość fizyczna, nie surowa (falsyfikator: odczyt
    bez skalowania daje wartości przesunięte o 32768)."""
    a = _ramp()
    a[0, 0] = 65000
    p = tmp_path / "u.fits"
    fits.PrimaryHDU(a).writeto(p)
    assert fits.getheader(p)["BZERO"] == 32768
    got = streaks.read_binned(p, 1)
    assert got.status == "ok" and got.native_shape == a.shape
    assert np.array_equal(got.data, a.astype(np.float32))


def test_fits_bscale_rozny_od_1(tmp_path):
    raw = (np.arange(30 * 50) % 1000).astype(np.int16).reshape(30, 50)
    hdu = fits.PrimaryHDU(raw)
    hdu.header["BSCALE"] = 2.5
    hdu.header["BZERO"] = 100.0
    p = tmp_path / "s.fits"
    hdu.writeto(p, output_verify="ignore")
    got = streaks.read_binned(p, 1)
    assert got.status == "ok"
    assert np.allclose(got.data, raw * 2.5 + 100.0)


def test_fits_binning_to_srednia_z_blokow(tmp_path):
    a = _ramp(41, 62)                                   # niepełne bloki na brzegu odpadają
    p = tmp_path / "b.fits"
    fits.PrimaryHDU(a).writeto(p)
    got = streaks.read_binned(p, 4)
    assert got.data.shape == (10, 15) and got.bin == 4 and got.native_shape == (41, 62)
    assert got.data[2, 3] == pytest.approx(a[8:12, 12:16].astype(np.float64).mean())


def test_fits_pusty_primary_i_obraz_w_rozszerzeniu(tmp_path):
    """Pierwszy HDU z obrazem 2D - nie „pierwsze NAXIS>0" (`scan._select_hdu`), które wybrałoby
    kostkę 3D stojącą przed obrazem."""
    img = _ramp()
    cube = np.zeros((3, 40, 60), np.uint16)
    p = tmp_path / "ext.fits"
    fits.HDUList([fits.PrimaryHDU(), fits.ImageHDU(cube), fits.ImageHDU(img)]).writeto(p)
    got = streaks.read_binned(p, 1)
    assert got.status == "ok"
    assert np.array_equal(got.data, img.astype(np.float32))


def test_fits_3d_bez_obrazu_2d(tmp_path):
    p = tmp_path / "cube.fits"
    fits.PrimaryHDU(np.zeros((3, 20, 30), np.float32)).writeto(p)
    assert streaks.read_binned(p, 2).status == "skipped:fits_3d"


@pytest.mark.filterwarnings("ignore:File may have been truncated")
def test_fits_uciety(tmp_path):
    p = tmp_path / "t.fits"
    fits.PrimaryHDU(_ramp(200, 300)).writeto(p)
    raw = p.read_bytes()
    p.write_bytes(raw[:len(raw) // 2])
    assert streaks.read_binned(p, 2).status == "error:truncated"


def test_raw_i_obcy_format(tmp_path):
    assert streaks.read_binned(tmp_path / "x.CR2", 4).status == "skipped:raw"
    assert streaks.read_binned(tmp_path / "x.png", 4).status == "skipped:format"


# ---------------------------------------------------------------- XISF

def test_deskryptor_xisf_wartosci_domyslne(tmp_path):
    p = _xisf(tmp_path / "d.xisf", _ramp().astype("<u2").tobytes(), "60:40:1", "UInt16")
    d = scan.xisf_image_descriptor(p)
    assert d == {"location": "attachment", "span": (BLOCK_AT, 40 * 60 * 2), "geometry": (60, 40, 1),
                 "sample_format": "UInt16", "byte_order": "little", "pixel_storage": "planar",
                 "compression": None}


def test_xisf_mono_little_endian(tmp_path):
    a = _ramp()
    p = _xisf(tmp_path / "le.xisf", a.astype("<u2").tobytes(), "60:40:1", "UInt16")
    got = streaks.read_binned(p, 1)
    assert got.status == "ok" and np.array_equal(got.data, a.astype(np.float32))


def test_xisf_mono_big_endian(tmp_path):
    """Falsyfikator: zignorowany `byteOrder` daje wartości z zamienionymi bajtami."""
    a = _ramp()
    p = _xisf(tmp_path / "be.xisf", a.astype(">u2").tobytes(), "60:40:1", "UInt16", byte_order="big")
    got = streaks.read_binned(p, 1)
    assert got.status == "ok" and np.array_equal(got.data, a.astype(np.float32))


def test_xisf_float32(tmp_path):
    a = (_ramp() / 65535.0).astype(np.float32)
    p = _xisf(tmp_path / "f.xisf", a.astype("<f4").tobytes(), "60:40:1", "Float32")
    got = streaks.read_binned(p, 2)
    assert got.status == "ok"
    assert np.allclose(got.data, a.reshape(20, 2, 30, 2).mean(axis=(1, 3)))


def _rgb():
    r = _ramp()
    g = r[::-1, ::-1].copy()
    b = np.full_like(r, 900)
    return r, g, b, (r.astype(np.float64) + g + b) / 3


def test_xisf_rgb_planar(tmp_path):
    r, g, b, lum = _rgb()
    p = _xisf(tmp_path / "rgbp.xisf", np.stack([r, g, b]).astype("<u2").tobytes(), "60:40:3", "UInt16")
    got = streaks.read_binned(p, 1)
    assert got.status == "ok" and np.allclose(got.data, lum, atol=1e-3)


def test_xisf_rgb_normal(tmp_path):
    """Kanały przeplatane piksel po pikselu; czytane jak planarne dałyby inną luminancję."""
    r, g, b, lum = _rgb()
    block = np.stack([r, g, b], axis=-1).astype("<u2").tobytes()
    p = _xisf(tmp_path / "rgbn.xisf", block, "60:40:3", "UInt16", storage="Normal")
    got = streaks.read_binned(p, 1)
    assert got.status == "ok" and np.allclose(got.data, lum, atol=1e-3)


def test_xisf_uciety_blok(tmp_path):
    block = _ramp().astype("<u2").tobytes()
    p = _xisf(tmp_path / "cut.xisf", block, "60:40:1", "UInt16", cut_at=BLOCK_AT + len(block) // 2)
    assert streaks.read_binned(p, 1).status == "error:truncated"


def test_xisf_skompresowany(tmp_path):
    block = _ramp().astype("<u2").tobytes()
    p = _xisf(tmp_path / "z.xisf", block, "60:40:1", "UInt16", compression=f"zlib:{len(block)}")
    assert streaks.read_binned(p, 1).status == "skipped:xisf_compressed"


def test_xisf_zly_naglowek_to_status_nie_wyjatek(tmp_path):
    p = tmp_path / "bad.xisf"
    p.write_bytes(b"NOTXISF!" + b"\0" * 64)
    assert streaks.read_binned(p, 1).status == "error:parse"
