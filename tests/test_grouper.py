"""Grouper teleskopów + config — integracja po skanie (po przejściu fitsmirror, brief §3).
Oś TELESKOP czytana WPROST z nagłówka: tożsamość = telescop_canon = TELESCOP.strip();
klastrowanie sygnatur FOCRATIO/FOCALLEN = MARTWE. Warianty wielkości liter foldowane WYŁĄCZNIE
przez collation NOCASE w repo (R2#8). Brak TELESCOP / brak kamery → config.review (W4)."""
import struct

import numpy as np
from astropy.io import fits

from horreum import db
from horreum.grouper import run_grouper
from horreum.scan import scan_tree

NOW = "2026-06-28T12:00:00"


def _fits(path, cards, n=0):
    """`n` różnicuje PIKSELE — po PF-2 tożsamość = sha1_data, więc identyczne dane zlałyby
    osobne klatki w jeden frame (multi-location)."""
    hdu = fits.PrimaryHDU(data=np.full((4, 4), n, np.uint16))
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
    """Drzewo: A140R (784/5.6) ×2 (w tym wariant casingu 'a140r') + ED120R (900/7.5) — ta sama
    kamera ASI2600MM; master flat XISF BEZ TELESCOP (→ config.review). Zwraca połączenie po skanie."""
    con = db.open_db(str(tmp_path / "h.db"))
    tree = tmp_path / "t"; tree.mkdir()
    cam = [("INSTRUME", "ZWO ASI2600MM Pro"), ("XPIXSZ", 3.76), ("IMAGETYP", "LIGHT")]
    _fits(tree / "a140r_1.fits", cam + [("TELESCOP", "A140R"), ("FOCALLEN", 784), ("FOCRATIO", 5.6)],
          n=1)
    _fits(tree / "a140r_2.fits", cam + [("TELESCOP", "a140r"), ("FOCALLEN", 784), ("FOCRATIO", 5.6)],
          n=2)                                                # wariant casingu → TEN SAM teleskop
    _fits(tree / "ed120r.fits", cam + [("TELESCOP", "ED120R"), ("FOCALLEN", 900), ("FOCRATIO", 7.5)],
          n=3)
    _xisf(tree / "mflat.xisf", [("INSTRUME", "'ZWO ASI2600MC Pro'"), ("XPIXSZ", "3.76"),
                                ("BAYERPAT", "'RGGB'"), ("IMAGETYP", "'Master Flat'")])  # bez TELESCOP
    scan_tree(con, tree, now=NOW)
    return con


def test_grouper_telescopy_z_naglowka_nocase_foldowane(tmp_path):
    """SEDNO po przejściu: teleskop = TELESCOP.strip(); 'A140R' i 'a140r' → JEDEN teleskop
    (foldowanie WYŁĄCZNIE przez NOCASE w repo — R2#8); ED120R osobno. Właściwości f//ogniskowa
    wypełnione z zeznań."""
    con = _scanned_tree(tmp_path)
    s = run_grouper(con, now=NOW)
    assert s.headers == 4 and s.telescopes_proposed == 2
    rows = {r["telescop_canon"]: r for r in con.execute(
        "SELECT telescop_canon, f_ratio_nominal, focal_nominal FROM telescope")}
    assert set(rows) == {"A140R", "ED120R"}                    # casing pierwszego wystąpienia
    assert (rows["A140R"]["f_ratio_nominal"], rows["A140R"]["focal_nominal"]) == (5.6, 784)
    assert (rows["ED120R"]["f_ratio_nominal"], rows["ED120R"]["focal_nominal"]) == (7.5, 900)
    con.close()


def test_grouper_config_link_inwariant_i_bez_telescop_review(tmp_path):
    """Lighty → config przypisany (inwariant config.camera_id==frame.camera_id); master BEZ
    TELESCOP → config_id NULL + event(config.review) + telescop_missing. Zero cichego NULL."""
    con = _scanned_tree(tmp_path)
    s = run_grouper(con, now=NOW)
    assert s.configs_proposed == 2 and s.configs_assigned == 3      # 2 configi, 3 lighty przypięte
    assert (s.telescop_missing, s.config_review) == (1, 1)
    linked = con.execute("SELECT count(*) FROM frame WHERE config_id IS NOT NULL").fetchone()[0]
    assert linked == 3
    assert con.execute("SELECT config_id FROM frame WHERE kind='master_flat'").fetchone()["config_id"] is None
    bad = con.execute("SELECT count(*) FROM frame f JOIN config c ON c.id=f.config_id "
                      "WHERE c.camera_id != f.camera_id").fetchone()[0]
    assert bad == 0
    assert con.execute("SELECT count(*) FROM event WHERE verb='config.review'").fetchone()[0] == 1
    con.close()


def _scanned_z_darkiem(tmp_path):
    """Jak `_scanned_tree`, plus masterdark XISF z TELESCOP='ED' (teleskop, który dark widzi tylko
    dlatego, że akwizycja wpisała pole sesji) — jedyne zeznanie o 'ED' w całym drzewie."""
    con = _scanned_tree(tmp_path)
    _xisf(tmp_path / "t" / "mdark.xisf",
          [("INSTRUME", "'ZWO ASI2600MM Pro'"), ("XPIXSZ", "3.76"), ("TELESCOP", "'ED'"),
           ("EXPTIME", "300.0"), ("IMAGETYP", "'Master Dark'")])
    scan_tree(con, tmp_path / "t", now=NOW)
    return con


def test_grouper_dark_nie_powoluje_teleskopu_ani_configu(tmp_path):
    """KIND-SCOPING (wariant B): masterdark z TELESCOP='ED' NIE tworzy teleskopu 'ED' (dark nie ma
    optyki — pole to ślad sesji), nie dostaje configu I NIE trafia do `config.review`. Jego
    `config_id IS NULL` to stan docelowy, nie delta. Flat/light zostają na osi bez zmian."""
    con = _scanned_z_darkiem(tmp_path)
    s = run_grouper(con, now=NOW)
    assert {r["telescop_canon"] for r in con.execute("SELECT telescop_canon FROM telescope")} \
        == {"A140R", "ED120R"}                                  # 'ED' NIE powstał
    assert s.calibration_off_axis == 1 and s.configs_unassigned == 0
    assert (s.telescop_missing, s.config_review) == (1, 1)      # nadal tylko masterflat bez TELESCOP
    assert con.execute(
        "SELECT config_id FROM frame WHERE kind='master_dark'").fetchone()["config_id"] is None
    assert con.execute("SELECT count(*) FROM event WHERE verb='config.review'").fetchone()[0] == 1
    con.close()


def test_grouper_odpina_stechle_przypisanie_kalibracji(tmp_path):
    """Dane SPRZED kind-scopingu: dark przypięty do cudzego configu. Przebieg AKTYWNIE go odpina
    (`config.unassigned`, ślad z poprzednim id), drugi przebieg jest już no-opem — samoleczenie
    idempotentne, bez migracji."""
    con = _scanned_z_darkiem(tmp_path)
    run_grouper(con, now=NOW)
    cfg_id = con.execute("SELECT id FROM config LIMIT 1").fetchone()["id"]
    con.execute("UPDATE frame SET config_id = ? WHERE kind='master_dark'", (cfg_id,))
    con.commit()                                                # symulacja stanu sprzed B

    s = run_grouper(con, now=NOW)
    assert s.configs_unassigned == 1
    assert con.execute(
        "SELECT config_id FROM frame WHERE kind='master_dark'").fetchone()["config_id"] is None
    ev = con.execute("SELECT payload, target FROM event WHERE verb='config.unassigned'").fetchall()
    assert len(ev) == 1 and str(cfg_id) in ev[0]["payload"]
    assert run_grouper(con, now=NOW).configs_unassigned == 0    # idempotencja
    assert con.execute(
        "SELECT count(*) FROM event WHERE verb='config.unassigned'").fetchone()[0] == 1
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
