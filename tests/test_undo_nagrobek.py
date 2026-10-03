"""AR-38 (1): cofnięcie commitu z kartą `OBJECT` ODTWARZA nagrobek ręki, który ten commit zgasił
(decyzja Zdzinia: „cofnięcie odtwarza wykluczenie").

Commit karty gasi nagrobek `user_cleared` i zeruje pamięć `object_cleared_id`; zgaszenie zapisuje
w zdarzeniu `object.tombstone_cleared` commit, plik i pamięć (`cleared_id`). Cofnięcie TEGO commitu
na TYM pliku odtwarza nagrobek w transakcji re-syncu (droga atomowa) albo dokończenia operacji
cofnięcia (droga w miejscu). Testy na prawdziwych plikach FITS, jak reszta baterii pisarza."""

from __future__ import annotations

import numpy as np
import pytest
from astropy.io import fits

from horreum import audit, db, repo, scan, writeback

NOW = "2026-10-03T00:00:00+00:00"


def _fits(path, *, obj="NGC6992"):
    hdu = fits.PrimaryHDU(data=np.arange(64, dtype=np.int16).reshape(8, 8))
    hdu.header["IMAGETYP"] = "Light"
    hdu.header["OBJECT"] = (obj, "Name of the object of interest")
    hdu.writeto(path, overwrite=True)
    return path


def _baza_z_nagrobkiem(tmp_path):
    """Plik w bazie, klatka cofnięta ręką z pamięcią obiektu `COS` (nagrobek z pamięcią)."""
    con = db.open_db(str(tmp_path / "h.db"))
    p = _fits(tmp_path / "a.fits")
    scan.ingest_record(con, scan.scan_file(str(p)), volume="V", now=NOW,
                       summary=scan.ScanSummary())
    loc = con.execute("SELECT id, frame_id FROM location WHERE path = ?", (str(p),)).fetchone()
    repo.user_assign_object(con, alias_norm=None, canon="COS", catalog=None, kind="own",
                            frame_ids=[loc["frame_id"]], now=NOW)
    repo.clear_object_assignment(con, frame_ids=[loc["frame_id"]], now=NOW)
    cos = con.execute("SELECT id FROM object WHERE canon = 'COS'").fetchone()[0]
    return con, p, loc["id"], loc["frame_id"], cos


def _commit_karty(con, lid, run, value="NGC 7000", *, inplace=False):
    hh = con.execute("SELECT header_hash FROM location WHERE id = ?", (lid,)).fetchone()[0]
    repo.stage_pending(con, run_id=run, location_id=lid, keyword="OBJECT", idx=0, op="set",
                       old_value=None, new_value=value, new_type="str", new_comment=None,
                       expected_header_hash=hh)
    res = writeback.commit(con, run, now=NOW, inplace=inplace)
    assert len(res.applied) == 1 and res.commit_id is not None, res
    return res


def _stan(con, fid):
    return tuple(con.execute("SELECT object_id, object_source, object_cleared_id FROM frame "
                             "WHERE id = ?", (fid,)).fetchone())


def _ev(con, verb):
    return con.execute("SELECT count(*) FROM event WHERE verb = ?", (verb,)).fetchone()[0]


@pytest.mark.parametrize("inplace", [False, True], ids=["atomowo", "w_miejscu"])
def test_cofniecie_odtwarza_nagrobek_z_pamiecia(tmp_path, inplace):
    """Sedno AR-38 w obu drogach pisarza. Falsyfikator: zdejmij `w_transakcji` z `_sync` (atomowo)
    albo gałąź `undo` z `repo.finish_inplace_op` (w miejscu) - klatka zostaje bez nagrobka,
    a najbliższy przebieg resolvera przypisze jej obiekt z karty, który ręka wykluczyła."""
    con, p, lid, fid, cos = _baza_z_nagrobkiem(tmp_path)
    res = _commit_karty(con, lid, "R", inplace=inplace)
    assert bool(res.in_place) is inplace
    assert _stan(con, fid) == (None, None, None)                      # commit zgasił nagrobek

    ures = writeback.undo(con, res.commit_id, now=NOW)
    assert len(ures.restored) == 1 and not ures.failed and not ures.blocked, ures
    assert fits.getheader(str(p))["OBJECT"] == "NGC6992"
    assert _stan(con, fid) == (None, "user_cleared", cos)             # wykluczenie wróciło
    assert _ev(con, "object.tombstone_restored") == 1
    if inplace:
        assert con.execute("SELECT count(*) FROM inplace_op WHERE kind = 'undo' "
                           "AND phase = 'synced'").fetchone()[0] == 1
    con.close()


def test_zgaszenie_niesie_commit_plik_i_pamiec(tmp_path):
    """Źródło odtworzenia: zdarzenie zgaszenia z parą (commit, plik) i pamięcią sprzed zgaszenia."""
    import json
    con, _p, lid, fid, cos = _baza_z_nagrobkiem(tmp_path)
    res = _commit_karty(con, lid, "R")
    payload, = [json.loads(r[0]) for r in con.execute(
        "SELECT payload FROM event WHERE verb = 'object.tombstone_cleared' AND target = ?",
        (f"frame:{fid}",))]
    assert payload == {"reason": "object_card_written", "cleared_id": cos,
                       "commit_id": res.commit_id, "location_id": lid}
    con.close()


def test_powtorne_cofniecie_nie_dubluje(tmp_path):
    """Drugie cofnięcie tego samego commitu jest 'blocked' („już cofnięte") i niczego nie pisze."""
    con, _p, lid, fid, cos = _baza_z_nagrobkiem(tmp_path)
    res = _commit_karty(con, lid, "R")
    writeback.undo(con, res.commit_id, now=NOW)
    ures = writeback.undo(con, res.commit_id, now=NOW)
    assert len(ures.blocked) == 1 and not ures.restored, ures
    assert _stan(con, fid) == (None, "user_cleared", cos)
    assert _ev(con, "object.tombstone_restored") == 1
    con.close()


def test_commit_cofniecie_commit_cofniecie_nie_gubi_ani_nie_dubluje(tmp_path):
    """Dwie pary commit/undo (dwa przebiegi stagingu): po każdej parze dokładnie jeden nagrobek
    z tą samą pamięcią; drugi commit gasi nagrobek ODTWORZONY, a jego cofnięcie znów go stawia."""
    con, _p, lid, fid, cos = _baza_z_nagrobkiem(tmp_path)
    for run in ("R1", "R2"):
        res = _commit_karty(con, lid, run)
        assert _stan(con, fid) == (None, None, None)
        ures = writeback.undo(con, res.commit_id, now=NOW)
        assert len(ures.restored) == 1, ures
        assert _stan(con, fid) == (None, "user_cleared", cos)
    assert (_ev(con, "object.tombstone_cleared"), _ev(con, "object.tombstone_restored")) == (2, 2)
    con.close()


def test_automat_po_commicie_odpiety_z_parytetem(tmp_path):
    """Między commitem a cofnięciem automat przypisał obiekt z karty (źródło nie-ręki). Odtworzenie
    go odpina i emituje `object.unassigned` - parytet §5.9 osi `frame.object_id` się domyka."""
    con, _p, lid, fid, cos = _baza_z_nagrobkiem(tmp_path)
    res = _commit_karty(con, lid, "R")
    ngc, _ = repo.upsert_object(con, canon="NGC 7000", catalog="NGC", kind="dso", now=NOW)
    repo.assign_object(con, frame_id=fid, object_id=ngc, object_source="header", now=NOW)
    writeback.undo(con, res.commit_id, now=NOW)
    assert _stan(con, fid) == (None, "user_cleared", cos)
    odpiecie = con.execute("SELECT payload, reason FROM event WHERE verb = 'object.unassigned' "
                           "ORDER BY id DESC LIMIT 1").fetchone()
    assert odpiecie["reason"] == "tombstone_restored" and f'"object_id": {ngc}' in odpiecie[0]
    oo = {p.name: p for p in audit.entity_event_parity(con)}["frame.object_id"]
    assert oo.entities == oo.events - oo.retracted, oo
    con.close()


@pytest.mark.parametrize("gest", ["przypisanie", "ponowne_cofniecie"])
def test_nowszy_werdykt_reki_nietkniety(tmp_path, gest):
    """Ręka po commicie przypisała obiekt albo cofnęła go ponownie (inna pamięć): cofnięcie
    commitu przywraca plik, a stan ręki zostaje co do bajtu."""
    con, _p, lid, fid, _cos = _baza_z_nagrobkiem(tmp_path)
    res = _commit_karty(con, lid, "R")
    repo.user_assign_object(con, alias_norm=None, canon="INNY", catalog=None, kind="own",
                            frame_ids=[fid], now=NOW)
    if gest == "ponowne_cofniecie":
        repo.clear_object_assignment(con, frame_ids=[fid], now=NOW)
    przed = _stan(con, fid)
    ures = writeback.undo(con, res.commit_id, now=NOW)
    assert len(ures.restored) == 1, ures
    assert _stan(con, fid) == przed
    assert _ev(con, "object.tombstone_restored") == 0
    con.close()


def test_nieudane_cofniecie_nie_odtwarza_a_ponowienie_tak(tmp_path, monkeypatch):
    """Re-sync cofnięcia padł ('failed'): nagłówek przywrócony, nagrobka NIE ma. Ponowne cofnięcie
    dokańcza synchronizację i odtwarza nagrobek razem z nią."""
    con, _p, lid, fid, cos = _baza_z_nagrobkiem(tmp_path)
    res = _commit_karty(con, lid, "R")
    prawdziwy = scan.scan_file

    def _czkawka(*a, **kw):
        raise OSError(5, "zerwany udział")
    monkeypatch.setattr(scan, "scan_file", _czkawka)
    ures = writeback.undo(con, res.commit_id, now=NOW)
    assert len(ures.failed) == 1 and not ures.restored, ures
    assert _stan(con, fid) == (None, None, None)
    monkeypatch.setattr(scan, "scan_file", prawdziwy)

    ures = writeback.undo(con, res.commit_id, now=NOW)
    assert len(ures.restored) == 1, ures
    assert _stan(con, fid) == (None, "user_cleared", cos)
    con.close()


def test_pad_odtworzenia_wycofuje_re_sync(tmp_path, monkeypatch):
    """Atomowość drogi atomowej: wyjątek przy odtworzeniu wycofuje też wciągnięcie rekordu, więc
    baza dalej opisuje plik po commicie, a ponowne cofnięcie robi oba zapisy naraz."""
    con, _p, lid, fid, cos = _baza_z_nagrobkiem(tmp_path)
    res = _commit_karty(con, lid, "R")
    hh_commitu = con.execute("SELECT header_hash FROM location WHERE id = ?", (lid,)).fetchone()[0]
    prawdziwy = repo.restore_object_tombstone

    def _pad(*a, **kw):
        raise RuntimeError("awaria w połowie")
    monkeypatch.setattr(repo, "restore_object_tombstone", _pad)
    ures = writeback.undo(con, res.commit_id, now=NOW)
    assert len(ures.failed) == 1, ures
    assert con.execute("SELECT header_hash FROM location WHERE id = ?",
                       (lid,)).fetchone()[0] == hh_commitu
    assert _stan(con, fid) == (None, None, None)
    monkeypatch.setattr(repo, "restore_object_tombstone", prawdziwy)

    ures = writeback.undo(con, res.commit_id, now=NOW)
    assert len(ures.restored) == 1, ures
    assert _stan(con, fid) == (None, "user_cleared", cos)
    con.close()


def test_zablokowane_cofniecie_nie_odtwarza(tmp_path):
    """Plik zmieniony od commitu: cofnięcie 'blocked', plik i nagrobek bez zmian."""
    con, p, lid, fid, _cos = _baza_z_nagrobkiem(tmp_path)
    res = _commit_karty(con, lid, "R")
    with fits.open(str(p), mode="update") as hdul:
        hdul[0].header["TELESCOP"] = "RC8"
    ures = writeback.undo(con, res.commit_id, now=NOW)
    assert len(ures.blocked) == 1 and not ures.restored, ures
    assert _stan(con, fid) == (None, None, None)
    assert _ev(con, "object.tombstone_restored") == 0
    con.close()


def test_commit_sprzed_AR38_cofa_sie_jak_dawniej(tmp_path, monkeypatch):
    """Dane wsadu zrobionego kodem sprzed AR-38: zgaszenie bez `commit_id` w payloadzie. Cofnięcie
    przywraca plik i NIE wywraca się; nagrobka nie odtwarza, bo nie wie, czy to ten commit go zgasił."""
    con, p, lid, fid, _cos = _baza_z_nagrobkiem(tmp_path)
    prawdziwy = repo.clear_object_tombstone
    monkeypatch.setattr(repo, "clear_object_tombstone",
                        lambda con_, *, frame_id, now, **_kw: prawdziwy(con_, frame_id=frame_id,
                                                                         now=now))
    res = _commit_karty(con, lid, "R")
    monkeypatch.setattr(repo, "clear_object_tombstone", prawdziwy)

    ures = writeback.undo(con, res.commit_id, now=NOW)
    assert len(ures.restored) == 1 and not ures.failed, ures
    assert fits.getheader(str(p))["OBJECT"] == "NGC6992"
    assert _stan(con, fid) == (None, None, None)
    assert _ev(con, "object.tombstone_restored") == 0
    con.close()


def test_commit_innej_karty_nie_odtwarza_niczego(tmp_path):
    """Commit bez karty `OBJECT` nagrobka nie gasił, więc jego cofnięcie nic nie odtwarza - także
    gdy klatka po drodze straciła nagrobek innym gestem."""
    con, _p, lid, fid, cos = _baza_z_nagrobkiem(tmp_path)
    hh = con.execute("SELECT header_hash FROM location WHERE id = ?", (lid,)).fetchone()[0]
    repo.stage_pending(con, run_id="T", location_id=lid, keyword="TELESCOP", idx=None, op="add",
                       old_value=None, new_value="RC8", new_type="str", new_comment=None,
                       expected_header_hash=hh)
    res = writeback.commit(con, "T", now=NOW)
    assert len(res.applied) == 1, res
    assert _stan(con, fid) == (None, "user_cleared", cos)
    writeback.undo(con, res.commit_id, now=NOW)
    assert _stan(con, fid) == (None, "user_cleared", cos)
    assert _ev(con, "object.tombstone_restored") == 0
    con.close()
