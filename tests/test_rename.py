"""Testy modułu „Nazwy z faktów" — rdzeń `horreum.naming` (Qt-wolny) + klinga `horreum.writeback`
(rename na PRAWDZIWYCH plikach) + `repo.relocate_location`.

Pokrycie: ekstraktory daty (header/filename, Z/ułamek/data-only, granice regexu), `resolve_dt`
(polityka wsadu + fallback), `compose_name` (kind-aware, dyskryminator sha1, brak daty→problem),
`run_rename` (multi-location/brak-kopii/nazwa-bez-zmian/kolizja-wsadu), pełny cykl stagingu→commit→
undo z realnym `os.rename`, ANTY-CLOBBER (dysk + baza, R3 #1/#3) i test BEHAWIORALNY kolizji (R3-P2 #7:
commit na istniejący cel → blocked, cel NIETKNIĘTY)."""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pytest
from astropy.io import fits

from horreum import db, naming, repo, scan, writeback

NOW = "2026-07-04T00:00:00+00:00"


# ============================================================ ekstraktory daty (§2)

def test_header_dt_iso_warianty():
    assert naming.header_dt("2024-03-15T21:30:45") == datetime(2024, 3, 15, 21, 30, 45)
    assert naming.header_dt("2024-03-15 21:30:45") == datetime(2024, 3, 15, 21, 30, 45)  # spacja
    assert naming.header_dt("2024-03-15T21:30:45.123Z") == datetime(2024, 3, 15, 21, 30, 45)  # Z+ułamek
    assert naming.header_dt("2024-03-15T21:30:45.9999") == datetime(2024, 3, 15, 21, 30, 45)


def test_header_dt_data_only_nie_polnoc():
    """R3 #10: data-only → None (zgłoszone jako brak czasu), NIGDY cicha północ."""
    assert naming.header_dt("2024-03-15") is None
    assert naming.header_dt("") is None
    assert naming.header_dt(None) is None
    assert naming.header_dt("śmieć") is None
    assert naming.header_dt("2024-13-40T99:99:99") is None  # nieprawidłowa data → None


def test_filename_dt_oba_wzorce():
    assert naming.filename_dt("Light_2024-03-15_21-30-45_Ha.fits") == datetime(2024, 3, 15, 21, 30, 45)
    assert naming.filename_dt("20240315_213045_M42.fits") == datetime(2024, 3, 15, 21, 30, 45)
    assert naming.filename_dt("brak_czasu.fits") is None


def test_filename_dt_granica_nie_lapie_dluzszej_liczby():
    """Granica `(?<!\\d)`/`(?!\\d)` broni przed startem w środku dłuższej liczby (fałszywy regex)."""
    assert naming.filename_dt("x20240315_213045.fits") == datetime(2024, 3, 15, 21, 30, 45)  # 'x' ok
    assert naming.filename_dt("1220240315_213045.fits") is None   # poprzedza cyfra → brak


def test_resolve_dt_polityka_i_offset():
    hdt, fdt = datetime(2024, 3, 15, 23, 0, 0), datetime(2024, 3, 15, 21, 0, 0)
    assert naming.resolve_dt(hdt, fdt, source="date_obs", offset_hours=0) == (hdt, None)
    assert naming.resolve_dt(hdt, fdt, source="filename", offset_hours=0) == (fdt, None)
    # offset pełno-godzinny (prawomocny czas innego stanowiska, NIE flaga)
    shifted, prob = naming.resolve_dt(hdt, fdt, source="date_obs", offset_hours=-2)
    assert shifted == datetime(2024, 3, 15, 21, 0, 0) and prob is None
    # brak wybranego źródła → problem
    dt, prob = naming.resolve_dt(None, fdt, source="date_obs", offset_hours=0)
    assert dt is None and "brak źródła" in prob


# ============================================================ compose_name (§1)

DT = datetime(2024, 3, 15, 21, 30, 45)
SHA = "abc123def456789000"


def test_compose_light_pelna_nazwa():
    facts = {"kind": "light", "object_canon": "NGC7000", "object_raw": "North America",
             "filter_canon": "Ha", "exptime": 300.0, "sha1_data": SHA, "ext": ".fits"}
    name, prob = naming.compose_name(facts, DT)
    assert prob is None
    assert name == "20240315_213045_NGC7000_light_Ha_300s_abc123def456.fits"


def test_compose_kalibracja_pomija_obiekt():
    """KIND-AWARE: kalibracja ma object_id=NULL z definicji → token obiektu POMINIĘTY (nie problem)."""
    facts = {"kind": "flat", "object_canon": None, "object_raw": "Flat",
             "filter_canon": "Ha", "exptime": 3.0, "sha1_data": SHA, "ext": ".fits"}
    name, prob = naming.compose_name(facts, DT)
    assert prob is None
    assert name == "20240315_213045_flat_Ha_3s_abc123def456.fits"


def test_compose_light_nierozwiazany_obiekt_unset():
    facts = {"kind": "light", "object_canon": None, "object_raw": None,
             "filter_canon": None, "exptime": None, "sha1_data": SHA, "ext": ".xisf"}
    name, prob = naming.compose_name(facts, DT)
    assert prob is None
    assert name == "20240315_213045__UNSET_light_abc123def456.xisf"   # filtr/exp pominięte


def test_compose_brak_daty_problem():
    facts = {"kind": "light", "sha1_data": SHA, "ext": ".fits"}
    name, prob = naming.compose_name(facts, None)
    assert name is None and "daty" in prob


def test_compose_sanityzacja_spacji():
    facts = {"kind": "light", "object_canon": "Heart of the Soul",
             "sha1_data": SHA, "ext": ".fits"}
    name, _ = naming.compose_name(facts, DT)
    assert " " not in name and "Heart_of_the_Soul" in name


# ============================================================ run_rename (§3) — fake targets_fn

def _row(**kw):
    base = {"frame_id": 1, "filetype": "fits", "kind": "light", "filter_canon": "Ha",
            "sha1_data": SHA, "object_canon": "NGC7000", "object_raw": None,
            "date_obs": "2024-03-15T21:30:45", "exptime": 300.0,
            "location_id": 10, "path": r"R:\A\old.fits", "mtime": "111"}
    base.update(kw)
    return base


def _targets(rows):
    by = {}
    for r in rows:
        by.setdefault(r["frame_id"], []).append(r)
    return lambda ids: [r for i in ids for r in by.get(i, [])]


def test_run_rename_podglad_ok():
    run = naming.run_rename([1], targets_fn=_targets([_row()]), source="date_obs", offset_hours=0)
    assert not run.skipped and len(run.touched) == 1
    p = run.touched[0]
    assert p.new_path == r"R:\A\20240315_213045_NGC7000_light_Ha_300s_abc123def456.fits"
    assert p.old_path == r"R:\A\old.fits" and p.mtime == "111"


def test_run_rename_multi_location_skip():
    rows = [_row(location_id=10), _row(location_id=11, path=r"R:\B\old.fits")]
    run = naming.run_rename([1], targets_fn=_targets(rows), source="date_obs", offset_hours=0)
    assert not run.touched and "multi-location" in run.skipped[0].reason


def test_run_rename_brak_kopii_skip():
    run = naming.run_rename([1], targets_fn=_targets([_row(location_id=None, path=None)]),
                            source="date_obs", offset_hours=0)
    assert not run.touched and "brak obecnej kopii" in run.skipped[0].reason


def test_run_rename_nazwa_bez_zmian_skip():
    tgt = _row(path=r"R:\A\20240315_213045_NGC7000_light_Ha_300s_abc123def456.fits")
    run = naming.run_rename([1], targets_fn=_targets([tgt]), source="date_obs", offset_hours=0)
    assert not run.touched and run.skipped[0].reason == "nazwa bez zmian"


def test_run_rename_kolizja_wsadu_skip():
    """Dwa różne frame'y → ten sam new_path (sha1 zduplikowany w danych wejściowych) → oba skip (R3 #4)."""
    rows = [_row(frame_id=1, location_id=10, path=r"R:\A\a.fits"),
            _row(frame_id=2, location_id=11, path=r"R:\A\b.fits")]
    run = naming.run_rename([1, 2], targets_fn=_targets(rows), source="date_obs", offset_hours=0)
    assert not run.touched
    assert all("kolizja nazwy w wsadzie" in s.reason for s in run.skipped)


def test_run_rename_fallback_source(monkeypatch):
    """D1: brak DATE-OBS → fallback na czas z nazwy, offset 0 (R2 #6)."""
    tgt = _row(date_obs=None, path=r"R:\A\Light_2024-03-15_21-30-45.fits")
    run = naming.run_rename([1], targets_fn=_targets([tgt]), source="date_obs", offset_hours=5)
    assert len(run.touched) == 1
    # fallback użył czasu z nazwy z offsetem 0 (NIE 5) → 21:30:45
    assert "20240315_213045" in run.touched[0].new_path


# ============================================================ integracja DB — migracja + relocate

def test_migracja_0005_pending_renames(tmp_path):
    con = db.open_db(str(tmp_path / "m.db"))
    assert con.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION >= 5
    cols = {r["name"] for r in con.execute("PRAGMA table_info(pending_renames)").fetchall()}
    assert {"run_id", "location_id", "old_path", "new_path", "expected_mtime", "status"} <= cols
    con.close()


def _seed_loc(con, path, volume="V"):
    fid, _ = repo.upsert_frame(con, sha1_data="s" + str(path), kind="light", filetype="fits",
                               camera_id=None, now=NOW)
    lid, _ = repo.add_location(con, frame_id=fid, volume=volume, path=str(path), mtime="111", now=NOW)
    return fid, lid


def test_relocate_location_update_i_event(tmp_path):
    con = db.open_db(str(tmp_path / "r.db"))
    _, lid = _seed_loc(con, r"R:\A\old.fits")
    assert repo.relocate_location(con, location_id=lid, new_path=r"R:\A\new.fits", now=NOW) is True
    assert con.execute("SELECT path FROM location WHERE id=?", (lid,)).fetchone()["path"] == r"R:\A\new.fits"
    ev = con.execute("SELECT verb, actor FROM event WHERE verb='location.renamed'").fetchone()
    assert ev["verb"] == "location.renamed" and ev["actor"] == "user:local"
    # idempotencja: ta sama ścieżka → False
    assert repo.relocate_location(con, location_id=lid, new_path=r"R:\A\new.fits", now=NOW) is False
    con.close()


def test_relocate_anty_clobber_baza(tmp_path):
    """R3 #3: cel zajęty przez INNY wiersz location(volume,path) → ValueError (UNIQUE-trap)."""
    con = db.open_db(str(tmp_path / "c.db"))
    _, lid_a = _seed_loc(con, r"R:\A\a.fits")
    _seed_loc(con, r"R:\A\b.fits")
    with pytest.raises(ValueError, match="cel zajęty"):
        repo.relocate_location(con, location_id=lid_a, new_path=r"R:\A\b.fits", now=NOW)
    con.close()


# ============================================================ pełny cykl na realnych plikach (klinga)

def _write_fits(path, **cards):
    hdu = fits.PrimaryHDU(data=np.zeros((4, 4), dtype=np.int16))
    for k, v in cards.items():
        hdu.header[k] = v
    hdu.writeto(path, overwrite=True)


def _scan_in(con, path, volume="V"):
    rec = scan.scan_file(str(path))
    scan.ingest_record(con, rec, volume=volume, now=NOW, summary=scan.ScanSummary())
    return con.execute("SELECT id, sha1_data FROM frame ORDER BY id DESC LIMIT 1").fetchone()


def _preview_and_stage(con, run_id, frame_ids):
    from horreum.gui import queries
    run = naming.run_rename(frame_ids, targets_fn=lambda ids: queries.rename_frame_targets(con, ids),
                            source="date_obs", offset_hours=0, run_id=run_id)
    for p in run.touched:
        repo.stage_rename(con, run_id=run_id, location_id=p.location_id, old_path=p.old_path,
                          new_path=p.new_path, expected_mtime=p.mtime)
    return run


def test_pelny_cykl_rename_commit_undo(tmp_path):
    con = db.open_db(str(tmp_path / "h.db"))
    p = tmp_path / "raw01.fits"
    _write_fits(p, IMAGETYP="Light", OBJECT="NGC7000", FILTER="Ha",
                **{"DATE-OBS": "2024-03-15T21:30:45", "EXPTIME": 300.0})
    fr = _scan_in(con, p)
    lid = con.execute("SELECT id FROM location WHERE path=?", (str(p),)).fetchone()["id"]

    run = _preview_and_stage(con, "RN", [fr["id"]])
    assert len(run.touched) == 1
    new_path = run.touched[0].new_path

    res = writeback.commit_renames(con, "RN", now=NOW)
    assert len(res.applied) == 1 and not res.blocked and not res.failed
    # plik na dysku PRZEMIANOWANY, stary zniknął
    import os
    assert os.path.exists(new_path) and not os.path.exists(str(p))
    # DB: location.path zaktualizowany IN-PLACE (ta sama location, tożsamość frame przeżywa)
    loc = con.execute("SELECT path, frame_id FROM location WHERE id=?", (lid,)).fetchone()
    assert loc["path"] == new_path and loc["frame_id"] == fr["id"]
    fr2 = con.execute("SELECT sha1_data FROM frame WHERE id=?", (fr["id"],)).fetchone()
    assert fr2["sha1_data"] == fr["sha1_data"]
    assert con.execute("SELECT 1 FROM event WHERE verb='location.renamed'").fetchone()

    # UNDO przywraca oryginalną nazwę
    ur = writeback.undo_renames(con, "RN", now=NOW)
    assert len(ur.restored) == 1 and not ur.blocked
    assert os.path.exists(str(p)) and not os.path.exists(new_path)
    assert con.execute("SELECT path FROM location WHERE id=?", (lid,)).fetchone()["path"] == str(p)
    con.close()


def test_commit_blocked_na_istniejacy_cel_nietkniety(tmp_path):
    """R3-P2 #7 BEHAWIORALNIE: commit renamu, gdy cel JUŻ istnieje na dysku (plik spoza bazy) →
    'blocked', a plik-cel NIETKNIĘTY. Meta-test AST nie odróżni os.replace/os.rename — chroni to zachowanie."""
    con = db.open_db(str(tmp_path / "b.db"))
    src = tmp_path / "raw02.fits"
    _write_fits(src, IMAGETYP="Light", OBJECT="M42", FILTER="OIII",
                **{"DATE-OBS": "2024-03-15T22:00:00", "EXPTIME": 120.0})
    fr = _scan_in(con, src)
    lid = con.execute("SELECT id FROM location WHERE path=?", (str(src),)).fetchone()["id"]

    run = naming.run_rename([fr["id"]], targets_fn=lambda ids: _qtargets(con, ids),
                            source="date_obs", offset_hours=0, run_id="B")
    new_path = run.touched[0].new_path
    # utwórz OBCY plik dokładnie pod celem (z innymi bajtami)
    with open(new_path, "wb") as f:
        f.write(b"OBCY-PLIK-NIE-RUSZAC")
    repo.stage_rename(con, run_id="B", location_id=lid, old_path=str(src), new_path=new_path,
                      expected_mtime=run.touched[0].mtime)

    res = writeback.commit_renames(con, "B", now=NOW)
    assert not res.applied and len(res.blocked) == 1
    import os
    assert os.path.exists(str(src))                       # źródło nietknięte
    with open(new_path, "rb") as f:
        assert f.read() == b"OBCY-PLIK-NIE-RUSZAC"        # cel NIETKNIĘTY (nie nadpisany)
    # DB niezmieniona
    assert con.execute("SELECT path FROM location WHERE id=?", (lid,)).fetchone()["path"] == str(src)
    con.close()


def _qtargets(con, ids):
    from horreum.gui import queries
    return queries.rename_frame_targets(con, ids)


# ============================================================ meta-test klingi zielony

def test_meta_test_klingi_przepuszcza_naming_i_rename():
    """naming.py NIE mutuje plików (silnik podglądu); rename żyje w writeback.py (DOOR). Import
    meta-testu i uruchomienie — offenders puste."""
    import test_writeback_safety as wbs
    wbs.test_mutacja_plikow_tylko_w_writeback()          # rzuci, gdyby naming.py był offenderem
