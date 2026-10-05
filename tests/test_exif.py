"""Czytnik EXIF DSLR/RAW (#2) — parser TIFF/EXIF, mapa na klucze FITS-owe, tożsamość=sha1 pliku,
strażnik GPS(0,0), kind z folderu, fold kamer, odmowa writebacku. Fikstury SYNTETYCZNE (bajty TIFF
budowane w teście) — deterministyczne, bez zależności od `R:`."""
import struct

import pytest

from horreum import exif, scan, writeback
from horreum.resolve.cameras import camera_identity, normalize_camera
from horreum.resolve.frames import kind_from_path
from horreum.resolve.observatory import site_coords


def build_raw(*, make="SONY", model="ILCE-7S", dto="2019:02:25 01:01:09", exptime=(29, 1),
              iso=3200, focal=None, lens=None, subsec=None, gps=None, magic=42, endian="<",
              ifd0_extra=(), exif_extra=(), subifds=()):
    """Zbuduj minimalny bajtowy TIFF/EXIF. Układ [header][ExifIFD][GPSIFD][SubIFD…][pula][IFD0] -
    IFD0 NA KOŃCU, jak realny DNG (ćwiczy seek po offsecie z końca). `gps` = (latref, [(n,d)×3],
    lonref, [(n,d)×3]) albo None. `ifd0_extra`/`exif_extra` = dodatkowe wpisy `(tag, typ, cnt,
    payload)`; `subifds` = listy takich wpisów - każda staje się SubIFD wskazanym z IFD0."""
    E = endian

    def ext(b):
        return ("ext", b)

    exif_e = [
        (exif._DTO, 2, len(dto) + 1, ext(dto.encode() + b"\x00")),
        (exif._EXPTIME, 5, 1, ext(struct.pack(E + "II", *exptime))),
        (exif._ISO, 3, 1, struct.pack(E + "H", iso)),
    ]
    if focal is not None:
        exif_e.append((exif._FOCAL, 5, 1, ext(struct.pack(E + "II", *focal))))
    if lens is not None:
        exif_e.append((exif._LENS, 2, len(lens) + 1, ext(lens.encode() + b"\x00")))
    if subsec is not None:
        exif_e.append((exif._SUBSEC, 2, len(subsec) + 1, ext(subsec.encode() + b"\x00")))
    exif_e.extend(exif_extra)

    gps_e = []
    if gps is not None:
        latref, lat, lonref, lon = gps
        gps_e = [
            (exif._GPS_LATREF, 2, 2, ext(latref.encode() + b"\x00")),
            (exif._GPS_LAT, 5, 3, ext(b"".join(struct.pack(E + "II", n, d) for n, d in lat))),
            (exif._GPS_LONREF, 2, 2, ext(lonref.encode() + b"\x00")),
            (exif._GPS_LON, 5, 3, ext(b"".join(struct.pack(E + "II", n, d) for n, d in lon))),
        ]

    ifd0_e = [
        (exif._MAKE, 2, len(make) + 1, ext(make.encode() + b"\x00")),
        (exif._MODEL, 2, len(model) + 1, ext(model.encode() + b"\x00")),
    ]
    ifd0_e.extend(ifd0_extra)

    def ifdsize(n):
        return 2 + n * 12 + 4

    off_exif = 8
    off_gps = off_exif + ifdsize(len(exif_e)) if gps_e else 0
    off_sub = off_exif + ifdsize(len(exif_e)) + (ifdsize(len(gps_e)) if gps_e else 0)
    sub_offs = []
    for s in subifds:
        sub_offs.append(off_sub)
        off_sub += ifdsize(len(s))
    pool_base = off_sub

    ifd0_e.append((exif._EXIF_IFD, 4, 1, struct.pack(E + "I", off_exif)))
    if gps_e:
        ifd0_e.append((exif._GPS_IFD, 4, 1, struct.pack(E + "I", off_gps)))
    if sub_offs:
        ifd0_e.append((exif._SUBIFDS, 4, len(sub_offs),
                       ext(b"".join(struct.pack(E + "I", o) for o in sub_offs))))

    pool = bytearray()

    def build_ifd(entries):
        body = struct.pack(E + "H", len(entries))
        for tag, typ, count, payload in entries:
            if isinstance(payload, tuple) and payload[0] == "ext":
                data = payload[1]
                if len(data) <= 4:                 # TIFF: wartość ≤4 B siedzi INLINE, nie w puli
                    val = (data + b"\x00\x00\x00\x00")[:4]
                else:
                    val = struct.pack(E + "I", pool_base + len(pool))
                    pool.extend(data)
            else:
                val = (payload + b"\x00\x00\x00\x00")[:4]
            body += struct.pack(E + "HHI", tag, typ, count) + val
        return body + struct.pack(E + "I", 0)      # next IFD = 0

    exif_b = build_ifd(exif_e)
    gps_b = build_ifd(gps_e) if gps_e else b""
    subs_b = b"".join(build_ifd(s) for s in subifds)
    ifd0_b = build_ifd(ifd0_e)
    off_ifd0 = pool_base + len(pool)
    sig = b"II" if E == "<" else b"MM"
    header = sig + struct.pack(E + "H", magic) + struct.pack(E + "I", off_ifd0)
    return bytes(header + exif_b + gps_b + subs_b + bytes(pool) + ifd0_b)


def write_raw(tmp_path, name="x.dng", **kw):
    p = tmp_path / name
    p.write_bytes(build_raw(**kw))
    return str(p)


# ── Czytnik: mapa EXIF → klucze FITS-owe ──

def test_czyta_pola_sony(tmp_path):
    p = write_raw(tmp_path, subsec="77")
    m = exif.read_exif_meta(p)
    assert m.header["INSTRUME"] == "SONY ILCE-7S"
    assert m.header["DATE-OBS"] == "2019-02-25T01:01:09.77"
    assert m.header["EXPTIME"] == "29.0"
    assert m.header["GAIN"] == "3200"


def test_ifd0_na_koncu_pliku(tmp_path):
    """DNG trzyma IFD0 na końcu — czytnik seekuje po offsecie z nagłówka (nie czoło pliku)."""
    p = write_raw(tmp_path)
    assert exif.read_exif_meta(p).header["INSTRUME"] == "SONY ILCE-7S"


def test_canon_instrume_bez_dublowania_marki(tmp_path):
    p = write_raw(tmp_path, make="Canon", model="Canon EOS 40D")
    assert exif.read_exif_meta(p).header["INSTRUME"] == "Canon EOS 40D"


def test_lens_myslniki_i_focal_zero_pomijane(tmp_path):
    p = write_raw(tmp_path, lens="----", focal=(0, 10))
    h = exif.read_exif_meta(p).header
    assert "TELESCOP" not in h and "FOCALLEN" not in h


def test_karty_lustro_1_1(tmp_path):
    p = write_raw(tmp_path)
    m = exif.read_exif_meta(p)
    assert {kw for kw, *_ in m.card_rows} == set(m.header)
    assert all(vt == "str" for _, _, _, _, vt, _ in m.card_rows)   # jak XISF


# ── Wymiary pełnego obrazu (AR-55): układy z sondy realnych plików 2026-10-05 ──

def _short(tag, v):
    return (tag, 3, 1, struct.pack("<H", v))


def _long(tag, v):
    return (tag, 4, 1, struct.pack("<I", v))


def _rat2(tag, a, b):
    return (tag, 5, 2, ("ext", struct.pack("<IIII", a, 1, b, 1)))


_MINIATURA = [_long(exif._NEWSUBFILE, 1), _short(exif._IMG_W, 256), _short(exif._IMG_H, 171)]


def test_wymiary_dng_z_defaultcropsize_obrazu_glownego(tmp_path):
    """DNG: IFD0 = miniatura 256×171, obraz główny w SubIFD (`NewSubFileType=0`) 4288×2848
    z `DefaultCropSize` 4240×2832 (A7S). Wygrywa kadr po wywołaniu, nie miniatura i nie brzeg."""
    p = write_raw(tmp_path, ifd0_extra=_MINIATURA, subifds=[
        [_long(exif._NEWSUBFILE, 0), _long(exif._IMG_W, 4288), _long(exif._IMG_H, 2848),
         _rat2(exif._CROP_SIZE, 4240, 2832)],
        [_long(exif._NEWSUBFILE, 1), _short(exif._IMG_W, 1024), _short(exif._IMG_H, 684)]])
    h = exif.read_exif_meta(p).header
    assert (h["NAXIS1"], h["NAXIS2"]) == ("4240", "2832")


def test_wymiary_arw_z_pixeldimension(tmp_path):
    """ARW: obraz główny bez `DefaultCropSize` - wygrywa `PixelX/YDimension` z ExifIFD (te same
    4240×2832 co DNG tej matrycy), nie `ImageWidth` z brzegiem."""
    p = write_raw(tmp_path, name="x.arw", ifd0_extra=[_long(exif._NEWSUBFILE, 1)],
                  exif_extra=[_short(exif._PIX_X, 4240), _short(exif._PIX_Y, 2832)],
                  subifds=[[_long(exif._NEWSUBFILE, 0), _short(exif._IMG_W, 4288),
                            _short(exif._IMG_H, 2848)]])
    h = exif.read_exif_header(p)
    assert (h["NAXIS1"], h["NAXIS2"]) == ("4240", "2832")


def test_wymiary_cr2_podglad_ifd0_bez_newsubfiletype_ignorowany(tmp_path):
    """CR2: IFD0 niesie podgląd 1936×1288 BEZ `NewSubFileType` - brak tagu nie jest zeznaniem
    o obrazie głównym. Wymiary z `PixelXDimension` (3888×2592, EOS 40D)."""
    p = write_raw(tmp_path, name="x.cr2", make="Canon", model="Canon EOS 40D",
                  ifd0_extra=[_short(exif._IMG_W, 1936), _short(exif._IMG_H, 1288)],
                  exif_extra=[_long(exif._PIX_X, 3888), _long(exif._PIX_Y, 2592)])
    h = exif.read_exif_header(p)
    assert (h["NAXIS1"], h["NAXIS2"]) == ("3888", "2592")


def test_wymiary_obraz_glowny_bez_kadru_i_bez_exif(tmp_path):
    """Ostatni szczebel: `ImageWidth`/`ImageLength` obrazu głównego. Orientacja zapisu zostaje
    (pion 2832×4240 nie jest obracany - dłuższy/krótszy bok rozstrzyga planer)."""
    p = write_raw(tmp_path, ifd0_extra=_MINIATURA, subifds=[
        [_long(exif._NEWSUBFILE, 0), _long(exif._IMG_W, 2832), _long(exif._IMG_H, 4240)]])
    h = exif.read_exif_header(p)
    assert (h["NAXIS1"], h["NAXIS2"]) == ("2832", "4240")


def test_wymiary_sama_miniatura_to_brak_faktu(tmp_path):
    """Plik bez obrazu głównego i bez ExifIFD-owych wymiarów: NAXIS nie powstaje - miniatura
    dałaby kadr 16× za duży, a brak faktu nie jest zerem."""
    p = write_raw(tmp_path, ifd0_extra=_MINIATURA)
    h = exif.read_exif_header(p)
    assert "NAXIS1" not in h and "NAXIS2" not in h


def test_wymiary_w_kartach_lustro_1_1_z_projekcja_liczbowa(tmp_path):
    p = write_raw(tmp_path, exif_extra=[_short(exif._PIX_X, 4240), _short(exif._PIX_Y, 2832)])
    m = exif.read_exif_meta(p)
    assert {kw for kw, *_ in m.card_rows} == set(m.header)
    num = {kw: n for kw, _, _, n, _, _ in m.card_rows}
    assert (num["NAXIS1"], num["NAXIS2"]) == (4240, 2832)


def test_nie_tiff_rzuca(tmp_path):
    p = tmp_path / "junk.dng"
    p.write_bytes(b"NOTATIFF" + b"\x00" * 40)
    with pytest.raises(ValueError):
        exif.read_exif_meta(str(p))


# ── Tożsamość: sha1 CAŁEGO pliku (D-R-1), uncomputable=0 ──

def test_tozsamosc_to_sha1_calego_pliku(tmp_path):
    p = write_raw(tmp_path)
    rec = scan.scan_file(p)
    assert rec.sha1_data == rec.file_sha1 and rec.sha1_data is not None


def test_scan_file_raw_bez_degeneracji(tmp_path):
    """RAW przez span=(0,filesize): sha1_data non-None → ingest NIE stawia uncomputable=1 (znal.3)."""
    from horreum.db import open_db
    con = open_db(":memory:")
    rec = scan.scan_file(write_raw(tmp_path))
    scan.ingest_record(con, rec, volume="V", now="2026-07-23T00:00:00", summary=scan.ScanSummary())
    row = con.execute("SELECT filetype, kind, kind_source, sha1_data_uncomputable FROM frame").fetchone()
    assert (row["filetype"], row["sha1_data_uncomputable"]) == ("raw", 0)
    assert (row["kind"], row["kind_source"]) == ("unknown", "path")   # tmp bez segmentu LIGHTS


# ── Dyspozycja formatu ──

def test_filetype_raw():
    assert scan._filetype("a.DNG") == "raw" and scan._filetype("a.arw") == "raw"
    assert scan._filetype("a.cr2") == "raw" and scan._filetype("a.fits") == "fits"


def test_read_header_dispatch_raw(tmp_path):
    p = write_raw(tmp_path)
    assert scan.read_header(p)["INSTRUME"] == "SONY ILCE-7S"


# ── kind z folderu (D-R-4) ──

@pytest.mark.parametrize("path,expected", [
    (r"R:\ASTRO_\LIGHTS\IC1318\portable\a.dng", "light"),
    (r"R:\ASTRO_\CALIBRATION\DARKS\a.dng", "dark"),
    (r"R:\ASTRO_\Flats\a.dng", "flat"),
    (r"R:\ASTRO_\bias\a.dng", "bias"),
    (r"R:\ASTRO_\NGC1318\a.dng", "unknown"),
])
def test_kind_from_path(path, expected):
    assert kind_from_path(path) == expected


# ── Fold kamer (D-R-5) + kolor przez raw_format ──

@pytest.mark.parametrize("instrume,canon", [
    ("SONY ILCE-7S", "SONYA7S"),
    ("SONY ILCE-7M3", "SONYA7M3"),
    ("SONY ILCE-7RM3A", "SONYA7RM3"),      # istniejący fold NIETKNIĘTY
    ("Canon EOS 40D", "CANONEOS40D"),
])
def test_fold_kamer_dslr(instrume, canon):
    assert normalize_camera(instrume) == canon
    assert normalize_camera(normalize_camera(instrume)) == canon   # idempotencja


def test_camera_identity_raw_format_kolor():
    ci = camera_identity({"INSTRUME": "SONY ILCE-7S"}, raw_format=True)
    assert ci.model_canon == "SONYA7S" and ci.is_mono == 0 and ci.is_mono_source == "raw_format"


def test_camera_identity_bez_raw_format_nietkniete():
    """FITS/XISF (raw_format=None) — DSLR bez BAYERPAT nadal review (zachowanie sprzed #2)."""
    ci = camera_identity({"INSTRUME": "SONY ILCE-7S"})
    assert ci.is_mono is None and ci.is_mono_source == "review"


# ── GPS(0,0) null island (§4) ──

def test_gps_zero_zero_to_null_island(tmp_path):
    z = [(0, 1), (0, 1), (0, 1)]
    p = write_raw(tmp_path, gps=("N", z, "E", z))
    h = exif.read_exif_meta(p).header
    assert h["SITELAT"] == "0.0" and h["SITELONG"] == "0.0"          # wierne zeznanie EXIF
    assert site_coords(h["SITELAT"], h["SITELONG"]) is None           # ale odrzucone


def test_gps_realny_zachowany(tmp_path):
    lat = [(50, 1), (12, 1), (30, 1)]      # 50°12'30" N
    lon = [(14, 1), (30, 1), (0, 1)]       # 14°30' E
    p = write_raw(tmp_path, gps=("N", lat, "E", lon))
    h = exif.read_exif_meta(p).header
    coords = site_coords(h["SITELAT"], h["SITELONG"])
    assert coords is not None
    assert abs(coords[0] - 50.2083) < 0.001 and abs(coords[1] - 14.5) < 0.001


def test_gps_polkula_poludniowa_zachodnia(tmp_path):
    d = [(10, 1), (0, 1), (0, 1)]
    p = write_raw(tmp_path, gps=("S", d, "W", d))
    h = exif.read_exif_meta(p).header
    assert site_coords(h["SITELAT"], h["SITELONG"]) == (-10.0, -10.0)


# ── Writeback ODMAWIA RAW (znal.4) ──

@pytest.mark.parametrize("name", ["x.dng", "x.arw", "x.cr2"])
def test_writeback_odmawia_raw(name):
    r = writeback.write_changes(name, [], None)
    assert r.status == "blocked" and "RAW" in r.reason


def test_writeback_full_header_odmawia_raw():
    assert writeback.write_full_header("x.dng", "TEXT", None).status == "blocked"
