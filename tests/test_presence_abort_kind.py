"""AR-62: powód zatrzymania passa obecności SPOZA hamulca niesie KOD (`abort_kind`) i pola liczbowe,
z których GUI składa zdanie w języku UI; polski `aborted` zostaje dla CLI. Realne drzewa FITS
w `tmp_path` (zero dotknięcia `R:`), wzorzec fixture z `test_presence_force.py`."""
import os
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits

from horreum import db, presence
from horreum.scan import scan_tree
from horreum.volumes import volume_serial

NOW = "2026-10-05T12:00:00"
LATER = "2026-10-05T18:00:00"


def _fits(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    hdu = fits.PrimaryHDU(data=np.full((4, 4), value, dtype=np.uint16))
    hdu.header["INSTRUME"] = "ZWO ASI2600MM Pro"
    hdu.header["IMAGETYP"] = "Light Frame"
    hdu.writeto(str(path))
    return path


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "ASTRO"
    paths = [str(_fits(root / "LIGHTS" / f"l{i}.fits", i + 1)) for i in range(4)]
    vol = volume_serial(str(root))
    if vol is None:
        pytest.skip("volume_serial nieustalony (nie-Windows) - pass wymaga trwałego serialu")
    con = db.open_db(str(tmp_path / "h.db"))
    scan_tree(con, str(root), volume=vol, now=NOW)
    yield con, str(root), vol, paths
    con.close()


def test_zdrowy_przebieg_bez_kodu_zatrzymania(tree):
    con, root, vol, paths = tree
    os.remove(paths[0])
    s = presence.check(con, root, volume=vol, apply=True, force=1, now=LATER)
    assert s.aborted is None and s.abort_kind is None
    assert s.serial == vol and s.force == 1


def test_wolumin_nieustalony(tree):
    con, root, vol, _paths = tree
    s = presence.check(con, root, volume="?", apply=True, now=LATER)
    assert s.abort_kind == "volume_unknown" and s.serial == vol and s.aborted is not None


def test_serial_nieczytelny(tree, monkeypatch):
    con, root, vol, _paths = tree
    monkeypatch.setattr(presence, "volume_serial", lambda _root: None)
    s = presence.check(con, root, volume=vol, apply=True, now=LATER)
    assert s.abort_kind == "serial_unreadable" and s.serial is None and s.aborted is not None


def test_serial_nieczytelny_przy_woluminie_nieustalonym(tree, monkeypatch):
    """Droga GUI: katalog osiągalny, `volume_serial` → None, worker podstawia `volume="?"`. Powód to
    nieczytelny serial, nie „pod … jest wolumin ?” (bramka sol S2)."""
    con, root, _vol, _paths = tree
    monkeypatch.setattr(presence, "volume_serial", lambda _root: None)
    s = presence.check(con, root, volume="?", apply=True, now=LATER)
    assert s.abort_kind == "serial_unreadable" and s.serial is None


def test_rozjazd_serialu(tree):
    con, root, vol, _paths = tree
    s = presence.check(con, root, volume="DEADBEEF", apply=True, now=LATER)
    assert s.abort_kind == "serial_mismatch" and s.serial == vol and s.volume == "DEADBEEF"


def test_rozjazd_deklaracji_force(tree):
    con, root, vol, paths = tree
    os.remove(paths[0])
    s = presence.check(con, root, volume=vol, apply=True, force=3, now=LATER)
    assert s.abort_kind == "force_mismatch" and (s.force, s.confirmed_gone) == (3, 1)
    assert s.vanished == 0 and "--force 3" in s.aborted       # CLI dalej dostaje polskie zdanie


def test_inny_zbior_niz_zatwierdzony(tree, monkeypatch):
    con, root, vol, paths = tree
    monkeypatch.setattr(presence, "_BRAKE_MIN", 1)
    os.remove(paths[0])
    os.remove(paths[1])
    d = presence.check(con, root, volume=vol, apply=False, confirm_under_brake=True, now=LATER)
    _fits(Path(paths[0]), 1)
    os.remove(paths[2])
    a = presence.check(con, root, volume=vol, apply=True, force=d.confirmed_gone,
                       expected_gone_ids=d.gone_ids, now=LATER)
    assert a.abort_kind == "gone_set_changed" and a.vanished == 0


def test_hamulec_bez_kodu_ma_wlasne_pola(tree):
    """Hamulec tłumaczy się z `brake`/`brake_limit` i liczników (AR-50 (1)) - kod zostaje `None`,
    żeby jeden fakt nie miał dwóch nośników."""
    con, root, vol, paths = tree
    for p in paths:
        os.remove(p)
    s = presence.check(con, root, volume=vol, apply=True, now=LATER)
    assert s.aborted == s.brake and s.abort_kind is None
