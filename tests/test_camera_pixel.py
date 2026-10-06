"""Piksel matrycy (AR-55 (2)-(3)): tolerancja zgodności zeznań, ręka silniejsza od skanu, cofnięcie
ręki do stanu sprzed pierwszego wpisu, planer bierze rękę przed kartą klatki, EXIF niesie piksel,
ponowny odczyt RAW przez bramę przyrostową."""
import json
import struct

import pytest

from horreum import cli, db, exif, repo, sky

NOW = "2026-10-06T10:00:00+00:00"


@pytest.fixture
def con(tmp_path):
    c = db.open_db(str(tmp_path / "h.db"))
    yield c
    c.close()


def _cam(con, model, pixel):
    cid, _ = repo.upsert_camera(con, model_canon=model, pixel_um=pixel, is_mono=0,
                                is_mono_source="raw_format", raw_instrume=model, now=NOW)
    return cid


def _stan(con, cid):
    r = con.execute("SELECT pixel_um, pixel_conflict, pixel_source FROM camera WHERE id = ?",
                    (cid,)).fetchone()
    return r["pixel_um"], r["pixel_conflict"], r["pixel_source"]


def _verbs(con, cid):
    return [r[0] for r in con.execute("SELECT verb FROM event WHERE target = ? ORDER BY id",
                                      (f"camera:{cid}",))]


# --- tolerancja -------------------------------------------------------------------------------

@pytest.mark.parametrize("a,b,zgodne", [(8.45, 8.469, True),     # A7S: karta vs EXIF, 0,2 %
                                        (4.62, 4.86, False),     # A7RM3: 5 % - sprzeczność
                                        (3.76, 3.76, True),
                                        (1000.0, 994.0, True),   # dokładnie na granicy 0,6 %
                                        (1000.0, 993.9, False)])  # tuż za nią (bramka sol Z5)
def test_pixel_agrees_tolerancja_wzgledna(a, b, zgodne):
    assert repo.pixel_agrees(a, b) is zgodne
    assert repo.pixel_agrees(b, a) is zgodne


def test_zeznanie_w_tolerancji_nie_robi_konfliktu(con):
    cid = _cam(con, "SONYA7S", 8.469)
    _cam(con, "SONYA7S", 8.45)
    assert _stan(con, cid) == (8.469, 0, None)
    assert _verbs(con, cid) == ["camera.upserted"]


def test_zeznanie_poza_tolerancja_to_konflikt(con):
    cid = _cam(con, "SONYA7RM3", 4.86)
    _cam(con, "SONYA7RM3", 4.62)
    assert _stan(con, cid) == (4.86, 1, None)


# --- ręka -------------------------------------------------------------------------------------

def test_reka_zdejmuje_konflikt_i_jest_silniejsza_od_skanu(con):
    cid = _cam(con, "SONYA7RM3", 4.86)
    _cam(con, "SONYA7RM3", 4.62)                                  # konflikt
    assert repo.set_camera_pixel(con, camera_id=cid, pixel_um=4.52, now=NOW) is True
    assert _stan(con, cid) == (4.52, 0, "user")
    _cam(con, "SONYA7RM3", 4.86)                                  # karta flatów NINA
    _cam(con, "SONYA7RM3", 4.62)                                  # EXIF
    assert _stan(con, cid) == (4.52, 0, "user")
    assert _verbs(con, cid)[-1] == "camera.pixel_user_set"


def test_reka_na_kamerze_bez_piksela_i_powtorny_wpis_cichy(con):
    cid = _cam(con, "SONYA7S", None)
    assert repo.set_camera_pixel(con, camera_id=cid, pixel_um=8.45, now=NOW) is True
    assert repo.set_camera_pixel(con, camera_id=cid, pixel_um=8.45, now=NOW) is False
    assert _verbs(con, cid).count("camera.pixel_user_set") == 1


@pytest.mark.parametrize("zla", [0, -1.0, None, "8.45"])
def test_reka_odmawia_wartosci_niedodatniej(con, zla):
    cid = _cam(con, "SONYA7S", None)
    with pytest.raises(ValueError):
        repo.set_camera_pixel(con, camera_id=cid, pixel_um=zla, now=NOW)
    assert _stan(con, cid) == (None, 0, None)


def test_cofniecie_wraca_do_stanu_sprzed_pierwszego_wpisu(con):
    cid = _cam(con, "SONYA7RM3", 4.86)
    _cam(con, "SONYA7RM3", 4.62)
    repo.set_camera_pixel(con, camera_id=cid, pixel_um=4.51, now=NOW)
    repo.set_camera_pixel(con, camera_id=cid, pixel_um=4.52, now=NOW)  # poprawka ręki
    assert repo.clear_camera_pixel(con, camera_id=cid, now=NOW) is True
    assert _stan(con, cid) == (4.86, 1, None)
    assert repo.clear_camera_pixel(con, camera_id=cid, now=NOW) is False
    # druga seria wpisów cofa się do stanu sprzed SWOJEGO pierwszego wpisu
    repo.set_camera_pixel(con, camera_id=cid, pixel_um=4.5, now=NOW)
    repo.clear_camera_pixel(con, camera_id=cid, now=NOW)
    assert _stan(con, cid) == (4.86, 1, None)
    last = con.execute("SELECT payload FROM event WHERE verb = 'camera.pixel_user_cleared' "
                       "ORDER BY id DESC LIMIT 1").fetchone()[0]
    assert json.loads(last)["pixel_um"] == 4.5


def test_po_cofnieciu_skan_znow_uzupelnia(con):
    cid = _cam(con, "SONYA7S", None)
    repo.set_camera_pixel(con, camera_id=cid, pixel_um=8.45, now=NOW)
    repo.clear_camera_pixel(con, camera_id=cid, now=NOW)
    _cam(con, "SONYA7S", 8.469)
    assert _stan(con, cid) == (8.469, 0, None)


# --- planer -----------------------------------------------------------------------------------

def _row(pixel, cam_pixel, cam_source=None, cam_conflict=0):
    return {"telescope": "T", "camera": "C", "focal": 135.0, "pixel": pixel,
            "cam_pixel": cam_pixel, "cam_conflict": cam_conflict, "cam_source": cam_source,
            "nx": 4240, "ny": 2832, "d": "2026-01-01"}


def test_planer_reka_przed_karta_klatki():
    rig = sky._rig_from_rows(1, [_row(4.62, 4.52, "user")])
    assert rig.pixel_um == 4.52 and rig.reason is None


def test_planer_bez_reki_karta_klatki_przed_kamera():
    rig = sky._rig_from_rows(1, [_row(8.469, 8.45)])
    assert rig.pixel_um == 8.469


def test_planer_klatka_bez_zeznania_bierze_kamere():
    rig = sky._rig_from_rows(1, [_row(None, 8.45)])
    assert rig.pixel_um == 8.45


# --- EXIF ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("res,unit,um", [(1180.7316589355469, 3, 8.469),     # A7S DNG
                                         (2164.4328002929688, 3, 4.62),      # A7RM3 DNG
                                         (4438.356164383562, 2, 5.723),      # 40D CR2 (cal)
                                         (0, 3, None), (1180.7, 7, None), (None, 3, None)])
def test_exif_piksel_z_rozdzielczosci_plaszczyzny(res, unit, um):
    assert exif._pixel_um(res, unit) == um


def _tiff_z_plaszczyzna(path, res_num, res_den, unit):
    """Minimalny TIFF LE: IFD0 (Make, Model, ExifIFD) + ExifIFD (FocalPlaneXResolution, Unit)."""
    make, model = b"SONY\x00", b"ILCE-7S\x00"
    ifd0_off = 8
    ifd0_n = 3
    ifd0_size = 2 + ifd0_n * 12 + 4
    data_off = ifd0_off + ifd0_size
    make_off, model_off = data_off, data_off + len(make)
    exif_off = model_off + len(model)
    exif_n = 2
    exif_size = 2 + exif_n * 12 + 4
    rat_off = exif_off + exif_size
    b = bytearray(b"II" + struct.pack("<HI", 42, ifd0_off))
    b += struct.pack("<H", ifd0_n)
    b += struct.pack("<HHII", 0x010F, 2, len(make), make_off)
    b += struct.pack("<HHII", 0x0110, 2, len(model), model_off)
    b += struct.pack("<HHII", 0x8769, 4, 1, exif_off)
    b += struct.pack("<I", 0)
    b += make + model
    b += struct.pack("<H", exif_n)
    b += struct.pack("<HHII", 0xA20E, 5, 1, rat_off)
    b += struct.pack("<HHI", 0xA210, 3, 1) + struct.pack("<HH", unit, 0)
    b += struct.pack("<I", 0)
    b += struct.pack("<II", res_num, res_den)
    path.write_bytes(bytes(b))


def test_exif_niesie_xpixsz_w_zeznaniu_i_karcie(tmp_path):
    p = tmp_path / "a.arw"
    _tiff_z_plaszczyzna(p, 11807316, 10000, 3)
    meta = exif.read_exif_meta(str(p))
    assert meta.header["XPIXSZ"] == "8.469"
    assert ("XPIXSZ", 0, "8.469", 8.469, "str", None) in meta.card_rows


# --- ponowny odczyt RAW ---------------------------------------------------------------------

def test_scan_reread_raw_odswieza_zeznanie_znanego_raw(tmp_path, monkeypatch):
    from horreum import scan
    root = tmp_path / "LIGHTS"
    root.mkdir()
    p = root / "a.arw"
    _tiff_z_plaszczyzna(p, 11807316, 10000, 3)
    c = db.open_db(str(tmp_path / "h.db"))
    try:
        # Pierwszy przebieg starym czytnikiem: bez piksela w zeznaniu.
        stary = exif.read_exif_meta

        def bez_piksela(path):
            m = stary(path)
            h = {k: v for k, v in m.header.items() if k != "XPIXSZ"}
            rows = [r for r in m.card_rows if r[0] != "XPIXSZ"]
            return exif.ExifMeta(header=h, card_rows=rows, header_hash=m.header_hash + "x")
        monkeypatch.setattr(exif, "read_exif_meta", bez_piksela)
        scan.scan_tree(c, str(root), volume="V1", now=NOW)
        monkeypatch.setattr(exif, "read_exif_meta", stary)

        def xpixsz():
            return c.execute("SELECT h.xpixsz FROM header h").fetchone()[0]
        assert xpixsz() is None
        s = scan.scan_tree(c, str(root), volume="V1", now=NOW)        # brama pomija
        assert s.skipped == 1 and xpixsz() is None
        s = scan.scan_tree(c, str(root), volume="V1", now=NOW, reread_raw=True)
        assert s.skipped == 0 and s.headers_refreshed == 1
        assert xpixsz() == pytest.approx(8.469)
        cam = c.execute("SELECT pixel_um FROM camera WHERE model_canon = 'SONYA7S'").fetchone()[0]
        assert cam == pytest.approx(8.469)
    finally:
        c.close()


# --- CLI --------------------------------------------------------------------------------------

def test_cli_camera_wpis_lista_i_cofniecie(tmp_path, capsys):
    path = str(tmp_path / "h.db")
    c = db.open_db(path)
    _cam(c, "SONYA7S", None)
    c.close()
    assert cli.main(["camera", path, "SONYA7S", "--pixel", "8.45"]) == 0
    assert cli.main(["camera", path]) == 0
    out = capsys.readouterr().out
    assert "wpisany reka" in out and "piksel 8.45 um" in out and "(reka)" in out
    assert cli.main(["camera", path, "SONYA7S", "--clear-pixel"]) == 0
    assert cli.main(["camera", path, "NIEMA", "--pixel", "1"]) == 2
    assert cli.main(["camera", path, "--pixel", "1"]) == 2
