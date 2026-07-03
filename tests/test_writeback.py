"""Testy `horreum.writeback` — druga klinga, na PRAWDZIWYCH plikach FITS (astropy).

Pełny cykl: skan pliku → staging → commit (os.replace) → undo. Weryfikuje: tożsamość `sha1_data`
PRZEŻYWA edycję nagłówka (brief T2), hash liczony z ZAPISANEGO pliku (T3), re-sync odświeża zeznanie
+ przelicza kamerę (R#2 — event frame.rederived), kontrola header_hash blokuje (T4), undo przywraca,
dwukrotne undo blocked, expected_header_hash blokuje stale-pending (R#7)."""

from __future__ import annotations

import numpy as np
import pytest
from astropy.io import fits

from horreum import db, repo, scan, writeback

NOW = "2026-07-03T00:00:00+00:00"


def _write_fits(path, **cards):
    """Zapisz minimalny plik FITS z danymi (identyczna sekcja danych = ta sama tożsamość)."""
    hdu = fits.PrimaryHDU(data=np.zeros((4, 4), dtype=np.int16))
    for k, v in cards.items():
        hdu.header[k] = v
    hdu.writeto(path, overwrite=True)


def _scan_in(con, path, volume="V"):
    """Zeskanuj realny plik do bazy (frame+location+header+cards spójne ze skanem)."""
    rec = scan.scan_file(str(path))
    scan.ingest_record(con, rec, volume=volume, now=NOW, summary=scan.ScanSummary())
    return con.execute("SELECT id, sha1_data FROM frame ORDER BY id DESC LIMIT 1").fetchone()


def _loc_id(con, path):
    return con.execute("SELECT id FROM location WHERE path = ?", (str(path),)).fetchone()["id"]


def _stage(con, run_id, location_id, keyword, op, new_value, new_type, *, idx=None, expected):
    return repo.stage_pending(
        con, run_id=run_id, location_id=location_id, keyword=keyword, idx=idx, op=op,
        old_value=None, new_value=new_value, new_type=new_type, new_comment=None,
        expected_header_hash=expected)


def test_commit_edits_header_and_preserves_identity(tmp_path):
    con = db.open_db(str(tmp_path / "h.db"))
    p = tmp_path / "a.fits"
    _write_fits(p, INSTRUME="ASI2600MM Pro", TELESCOP="RC8", IMAGETYP="Light")
    fr = _scan_in(con, p)
    lid = _loc_id(con, p)
    hh = con.execute("SELECT header_hash FROM location WHERE id=?", (lid,)).fetchone()["header_hash"]

    _stage(con, "R", lid, "TELESCOP", "set", "SkyWatcher RC8", "str", expected=hh)
    res = writeback.commit(con, "R", now=NOW)

    assert len(res.applied) == 1 and not res.blocked and not res.failed
    # plik na dysku ZMIENIONY
    assert fits.getheader(str(p))["TELESCOP"] == "SkyWatcher RC8"
    # tożsamość frame PRZEŻYWA (sha1_data ten sam — dane nietknięte)
    fr2 = con.execute("SELECT id, sha1_data FROM frame WHERE id=?", (fr["id"],)).fetchone()
    assert fr2["sha1_data"] == fr["sha1_data"]
    # zeznanie odświeżone (header.telescop nowy), header_hash location zmieniony
    hdr = con.execute("SELECT telescop FROM header WHERE frame_id=?", (fr["id"],)).fetchone()
    assert hdr["telescop"] == "SkyWatcher RC8"
    hh2 = con.execute("SELECT header_hash FROM location WHERE id=?", (lid,)).fetchone()["header_hash"]
    assert hh2 and hh2 != hh
    # event mutacji pliku wyemitowany z actor=user:local (nie skan)
    evs = con.execute("SELECT verb FROM event WHERE actor='user:local'").fetchall()
    assert any(e["verb"] == "header.refreshed" for e in evs)
    con.close()


def test_commit_then_undo_restores(tmp_path):
    con = db.open_db(str(tmp_path / "h.db"))
    p = tmp_path / "b.fits"
    _write_fits(p, TELESCOP="RC8", IMAGETYP="Light")
    fr = _scan_in(con, p)
    lid = _loc_id(con, p)
    hh = con.execute("SELECT header_hash FROM location WHERE id=?", (lid,)).fetchone()["header_hash"]

    _stage(con, "R", lid, "TELESCOP", "set", "EQ6", "str", expected=hh)
    cres = writeback.commit(con, "R", now=NOW)
    assert cres.commit_id is not None
    assert fits.getheader(str(p))["TELESCOP"] == "EQ6"

    ures = writeback.undo(con, cres.commit_id, now=NOW)
    assert len(ures.restored) == 1 and not ures.blocked
    assert fits.getheader(str(p))["TELESCOP"] == "RC8"       # przywrócone

    # dwukrotne undo → blocked (nagłówek != post_hash po pierwszym undo)
    ures2 = writeback.undo(con, cres.commit_id, now=NOW)
    assert len(ures2.blocked) == 1 and not ures2.restored
    con.close()


def test_header_hash_mismatch_blocks(tmp_path):
    con = db.open_db(str(tmp_path / "h.db"))
    p = tmp_path / "c.fits"
    _write_fits(p, TELESCOP="RC8", IMAGETYP="Light")
    _scan_in(con, p)
    lid = _loc_id(con, p)

    # expected_header_hash celowo ZŁY → write_changes blokuje, plik NIETKNIĘTY
    _stage(con, "R", lid, "TELESCOP", "set", "EQ6", "str", expected="deadbeef")
    res = writeback.commit(con, "R", now=NOW)
    assert len(res.blocked) == 1 and not res.applied
    assert fits.getheader(str(p))["TELESCOP"] == "RC8"       # niezmieniony
    con.close()


def test_stale_pending_blocked_after_external_change(tmp_path):
    """R#7: plik zmieniony (re-skan) MIĘDZY stagingiem a commitem → expected_header_hash ≠ bieżący
    → blocked. Symulujemy edycją nagłówka poza writebackiem + re-skanem."""
    con = db.open_db(str(tmp_path / "h.db"))
    p = tmp_path / "d.fits"
    _write_fits(p, TELESCOP="RC8", IMAGETYP="Light")
    _scan_in(con, p)
    lid = _loc_id(con, p)
    hh = con.execute("SELECT header_hash FROM location WHERE id=?", (lid,)).fetchone()["header_hash"]
    _stage(con, "R", lid, "FOCALLEN", "add", "600", "int", expected=hh)

    # ktoś zmienia plik i re-skan aktualizuje location.header_hash (stary staging = stęchły)
    _write_fits(p, TELESCOP="RC8", IMAGETYP="Light", GAIN=100)
    _scan_in(con, p)
    res = writeback.commit(con, "R", now=NOW)
    assert len(res.blocked) == 1 and not res.applied
    con.close()


def test_gone_copy_skipped(tmp_path):
    con = db.open_db(str(tmp_path / "h.db"))
    p = tmp_path / "e.fits"
    _write_fits(p, TELESCOP="RC8", IMAGETYP="Light")
    _scan_in(con, p)
    lid = _loc_id(con, p)
    hh = con.execute("SELECT header_hash FROM location WHERE id=?", (lid,)).fetchone()["header_hash"]
    _stage(con, "R", lid, "TELESCOP", "set", "EQ6", "str", expected=hh)
    # oznacz kopię jako zniknętą przez repo? present ustawiamy wprost (test poza bramką)
    con.execute("UPDATE location SET present=0 WHERE id=?", (lid,))
    con.commit()
    res = writeback.commit(con, "R", now=NOW)
    assert len(res.skipped) == 1 and not res.applied
    con.close()
