"""Grouper teleskopów + config — integracja po skanie (§Etap 5).
Kryteria §5.4/§5.5: A140R (f/5.6) ODDZIELNIE od ED120 (f/6.4) mimo nakładających się ogniskowych;
mastery bez FOCRATIO → config.review (W4); link frame.config_id z inwariantem §1; idempotencja."""
import struct

import numpy as np
from astropy.io import fits

from horreum import db
from horreum.grouper import run_grouper
from horreum.scan import scan_tree

NOW = "2026-06-28T12:00:00"


def _fits(path, cards):
    hdu = fits.PrimaryHDU(data=np.zeros((4, 4), np.uint16))
    for kw, val in cards:
        hdu.header[kw] = val
    fits.HDUList([hdu]).writeto(str(path))
    return path


def _xisf(path, keywords):
    parts = "".join(f'<FITSKeyword name="{n}" value="{v}" comment=""/>' for n, v in keywords)
    xml = (f'<xisf version="1.0" xmlns="http://www.pixinsight.com/xisf">'
           f'<Image geometry="4:4:1" sampleFormat="UInt16" location="attachment:0:32">'
           f'{parts}</Image></xisf>').encode("utf-8")
    with open(path, "wb") as fh:
        fh.write(b"XISF0100"); fh.write(struct.pack("<I", len(xml))); fh.write(b"\x00" * 4)
        fh.write(xml); fh.write(b"\x00" * 32)
    return path


def _scanned_tree(tmp_path):
    """Drzewo: A140R (f/5.6, 784) + ED120 (f/6.4, 768) — ta sama kamera ASI2600MM; master flat
    XISF bez FOCRATIO (→ config.review). Zwraca otwarte połączenie po skanie."""
    con = db.open_db(str(tmp_path / "h.db"))
    tree = tmp_path / "t"; tree.mkdir()
    _fits(tree / "a140r.fits", [("INSTRUME", "ZWO ASI2600MM Pro"), ("XPIXSZ", 3.76),
                                ("FOCALLEN", 784), ("FOCRATIO", 5.6), ("IMAGETYP", "LIGHT"),
                                ("TELESCOP", "A140R")])
    _fits(tree / "ed120.fits", [("INSTRUME", "ZWO ASI2600MM Pro"), ("XPIXSZ", 3.76),
                                ("FOCALLEN", 768), ("FOCRATIO", 6.4), ("IMAGETYP", "LIGHT"),
                                ("TELESCOP", "ED120")])
    _xisf(tree / "mflat.xisf", [("INSTRUME", "'ZWO ASI2600MC Pro'"), ("XPIXSZ", "3.76"),
                                ("BAYERPAT", "'RGGB'"), ("IMAGETYP", "'Master Flat'")])  # bez FOCRATIO
    scan_tree(con, tree, now=NOW)
    return con


def test_grouper_a140r_oddzielnie_od_ed120(tmp_path):
    """SEDNO §5.4: różne f/ → DWA teleskopy mimo nakładających się ogniskowych (784 vs 768)."""
    con = _scanned_tree(tmp_path)
    s = run_grouper(con, now=NOW)
    assert s.telescopes_proposed == 2
    fr = {r[0] for r in con.execute("SELECT f_ratio_nominal FROM telescope")}
    assert fr == {5.6, 6.4}
    assert con.execute("SELECT count(*) FROM telescope").fetchone()[0] == 2
    con.close()


def test_grouper_focratio_backfill_i_recovered(tmp_path):
    """focratio_norm backfillowany w header: lights ok (5.6/6.4), master bez FOCRATIO → review."""
    con = _scanned_tree(tmp_path)
    s = run_grouper(con, now=NOW)
    assert (s.focratio_ok, s.focratio_review) == (2, 1)
    norms = sorted(r[0] for r in con.execute("SELECT focratio_norm FROM header WHERE focratio_norm IS NOT NULL"))
    assert norms == [5.6, 6.4]
    # master flat → focratio_norm NULL + src review
    m = con.execute("SELECT focratio_norm, focratio_norm_src FROM header h JOIN frame f ON f.id=h.frame_id "
                    "WHERE f.kind='master_flat'").fetchone()
    assert (m["focratio_norm"], m["focratio_norm_src"]) == (None, "review")
    con.close()


def test_grouper_config_link_inwariant_i_master_review(tmp_path):
    """Lights → config przypisany (inwariant config.camera_id==frame.camera_id); master bez
    focratio → config_id NULL + event(config.review). Zero cichego NULL."""
    con = _scanned_tree(tmp_path)
    s = run_grouper(con, now=NOW)
    assert s.configs_proposed == 2 and s.configs_assigned == 2 and s.config_review == 1
    # lights: config_id NOT NULL; master: NULL
    linked = con.execute("SELECT count(*) FROM frame WHERE config_id IS NOT NULL").fetchone()[0]
    assert linked == 2
    assert con.execute("SELECT config_id FROM frame WHERE kind='master_flat'").fetchone()["config_id"] is None
    # INWARIANT §1: każdy frame z config_id ma config.camera_id == frame.camera_id
    bad = con.execute("SELECT count(*) FROM frame f JOIN config c ON c.id=f.config_id "
                      "WHERE c.camera_id != f.camera_id").fetchone()[0]
    assert bad == 0
    # master → config.review (jawnie)
    assert con.execute("SELECT count(*) FROM event WHERE verb='config.review'").fetchone()[0] == 1
    con.close()


def test_grouper_idempotentny(tmp_path):
    """Drugi przebieg grouper nie tworzy duplikatów teleskopów/configów (propose_* idempotentne)."""
    con = _scanned_tree(tmp_path)
    run_grouper(con, now=NOW)
    s2 = run_grouper(con, now=NOW)
    assert s2.telescopes_proposed == 0 and s2.configs_proposed == 0 and s2.configs_assigned == 0
    assert con.execute("SELECT count(*) FROM telescope").fetchone()[0] == 2
    assert con.execute("SELECT count(*) FROM config").fetchone()[0] == 2
    con.close()
