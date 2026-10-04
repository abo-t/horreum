"""Testy ZAPISU W MIEJSCU (O5, 2026-09-26) - pisarz `writeback.write_changes_inplace` pod blokadą,
dziennik operacji `inplace_op` (0022), `commit(inplace=True)`, undo w miejscu i atomowo, odzysk
rozdartego nagłówka (`recover_torn`), izolacja lokacji od skanu, oraz plan ujednolicenia karty
`OBJECT` (`queries.object_card_form_rows` + `macro.plan_object_card_form` + `repo.stage_pending_many`).

Pliki FITS/XISF SYNTETYCZNE w `tmp_path` (bateria hermetyczna). Scenariusze P1 z recenzji astry
(Z11 kontrprzykład przebudowy, Z12 prawdziwy stary backup tekstowy, Z13 przerwane undo XISF
z wypełnieniem) są tu dosłownie - bez poprawki padają."""

from __future__ import annotations

import dataclasses
import importlib.util
import json
import os
import sqlite3
import struct
import tempfile
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits

from horreum import db, macro, repo, resolver, scan, writeback
from horreum.gui import queries

NOW = "2026-09-26T00:00:00+00:00"
KOMENTARZ = "Name of the object of interest"


def _fits(path, *, obj="NGC6992", seed=0, extra=(), comment=KOMENTARZ, dane=None):
    """FITS z kartą OBJECT (z komentarzem jak u NINA) i danymi zależnymi od `seed` (tożsamość)."""
    if dane is None:
        dane = (np.arange(64, dtype=np.int16).reshape(8, 8) + seed).astype(np.int16)
    hdu = fits.PrimaryHDU(data=dane)
    hdu.header["IMAGETYP"] = "Light"
    hdu.header["OBJECT"] = (obj, comment)
    for k, v in extra:
        hdu.header.append((k, v))
    hdu.writeto(path, overwrite=True)
    return path


def _xisf(path, *, obj="'NGC6992'", comment="nazwa obiektu", pad=64, payload=b"\x07" * 32,
          props="", wypelnienie=b"\x00"):
    """Monolityczny XISF: XML + REZERWA `pad` + attachment (offset na stałej szerokości)."""
    def body(start):
        kw = (f'<FITSKeyword name="IMAGETYP" value="\'Light\'" comment=""/>'
              f'<FITSKeyword name="OBJECT" value="{obj}" comment="{comment}"/>')
        return ('<?xml version="1.0" encoding="UTF-8"?>'
                '<xisf version="1.0" xmlns="http://www.pixinsight.com/xisf">' + props
                + f'<Image geometry="4:4:1" sampleFormat="UInt16" '
                  f'location="attachment:{start:08d}:{len(payload)}">{kw}</Image></xisf>'
                ).encode("utf-8")
    xml = body(scan.XISF_XML_OFFSET + len(body(0)) + pad)
    with open(path, "wb") as fh:
        fh.write(b"XISF0100" + struct.pack("<I", len(xml)) + b"\x00" * 4 + xml
                 + wypelnienie * pad + payload)
    return path


def _op(value="NGC 6992"):
    return [writeback.WriteOp("OBJECT", "set", value, "str", idx=0)]


def _hash(path):
    return scan.scan_file(str(path)).header_hash


class _Dziennik:
    """Dziennik testowy pisarza: zapamiętuje operację, stan pliku w chwili `begin` i fazy."""

    def __init__(self, path=None, pada=False):
        self.path, self.pada = path, pada
        self.spec = self.backup_text = self.plik_przy_begin = None
        self.fazy = []

    def begin(self, spec, backup_text):
        if self.pada:
            raise sqlite3.OperationalError("database is locked")
        self.spec, self.backup_text = spec, backup_text
        if self.path is not None:
            self.plik_przy_begin = Path(self.path).read_bytes()

    def phase(self, faza, reason=None):
        self.fazy.append(faza)


class _NieWolno:
    def begin(self, spec, backup_text):
        raise AssertionError("dziennik nie powinien zostać otwarty")

    def phase(self, faza, reason=None):
        raise AssertionError("dziennik nie powinien zostać otwarty")


def _scan_in(con, path, volume="V"):
    rec = scan.scan_file(str(path))
    scan.ingest_record(con, rec, volume=volume, now=NOW, summary=scan.ScanSummary())


def _loc(con, path):
    return con.execute("SELECT id, header_hash, frame_id FROM location WHERE path = ?",
                       (str(path),)).fetchone()


def _stage(con, run_id, lid, value, expected):
    repo.stage_pending(con, run_id=run_id, location_id=lid, keyword="OBJECT", idx=0, op="set",
                       old_value=None, new_value=value, new_type="str", new_comment=None,
                       expected_header_hash=expected)


def _baza_z_plikiem(tmp_path, plik):
    con = db.open_db(str(tmp_path / "h.db"))
    _scan_in(con, plik)
    loc = _loc(con, plik)
    _stage(con, "R", loc["id"], "NGC 6992", loc["header_hash"])
    return con, loc


def _operacje(con):
    return con.execute("SELECT id, kind, phase FROM inplace_op ORDER BY id").fetchall()


def _psuj_fsync(monkeypatch):
    """Weryfikacja po zapisie ma się rozjechać: `fsync` rzuca PO zapisie → faza `unverified`."""
    prawdziwy = os.fsync

    def _fsync(fd):
        prawdziwy(fd)
        raise OSError(64, "The specified network name is no longer available")
    monkeypatch.setattr(writeback.os, "fsync", _fsync)


# ============================================================ PISARZ FITS W MIEJSCU


def test_fits_podmienia_jedna_karte_w_tym_samym_slocie_z_komentarzem(tmp_path):
    """Jedyne zmienione bajty leżą w 80-bajtowym slocie karty OBJECT; długość nagłówka, rozmiar
    pliku i dane bez zmian; zastany komentarz zostaje (AR-7); dziennik dostaje operację z regionem
    starym/nowym i zakresem zapisu w slocie, backup = surowy region; `st_ino` bez zmian."""
    p = _fits(tmp_path / "a.fits")
    przed = p.read_bytes()
    ino = os.stat(p).st_ino
    dz = _Dziennik()
    res = writeback.write_changes_inplace(str(p), _op(), _hash(p), journal=dz)

    assert res.status == "applied" and res.in_place, res
    po = p.read_bytes()
    assert len(po) == len(przed) and os.stat(p).st_ino == ino
    rozne = [i for i in range(len(po)) if po[i] != przed[i]]
    slot = przed.index(b"OBJECT  = ")
    assert slot % 80 == 0 and rozne and slot <= rozne[0] and rozne[-1] < slot + 80
    hdr = fits.getheader(str(p))
    assert hdr["OBJECT"] == "NGC 6992" and hdr.comments["OBJECT"] == KOMENTARZ
    s = dz.spec
    assert (s.region_offset, s.old_region, s.new_region) == (0, przed[:2880], po[:2880])
    assert slot <= s.write_start < s.write_end <= slot + 80
    assert (s.file_size, s.file_ino) == (len(przed), ino) and s.post_hash == _hash(p)
    env = writeback.RegionBackup.decode(dz.backup_text)
    assert env.region == przed[:2880] and res.backup_text == dz.backup_text
    assert dz.fazy == ["written"]


def test_fits_zly_hash_blokuje_bez_zapisu_i_bez_dziennika(tmp_path):
    p = _fits(tmp_path / "b.fits")
    przed = p.read_bytes()
    res = writeback.write_changes_inplace(str(p), _op(), "deadbeef", journal=_NieWolno())
    assert res.status == "blocked" and res.reason == "header_hash mismatch"
    assert p.read_bytes() == przed and not res.in_place and res.backup_text is None


def test_dziennik_powstaje_przed_zapisem_a_jego_porazka_nie_rusza_pliku(tmp_path):
    p = _fits(tmp_path / "c.fits")
    przed = p.read_bytes()
    dz = _Dziennik(path=p)
    assert writeback.write_changes_inplace(str(p), _op(), _hash(p), journal=dz).status == "applied"
    assert dz.plik_przy_begin == przed

    q = _fits(tmp_path / "c2.fits")
    przed_q = q.read_bytes()
    res = writeback.write_changes_inplace(str(q), _op(), _hash(q), journal=_Dziennik(pada=True))
    assert res.status == "failed" and "NIE powstał" in res.reason
    assert q.read_bytes() == przed_q and res.backup_text is None and not res.in_place


@pytest.mark.parametrize("opis, plik, ops, fragment", [
    ("dwie karty OBJECT",
     lambda tp: _fits(tp / "d.fits", extra=[("OBJECT", "NGC6992")]), _op(), "występuje 2 razy"),
    ("komentarz nie zmieści się przy nowej wartości",
     lambda tp: _fits(tp / "e.fits", obj="M31", comment="k" * 47), _op("V" * 20), "nie mieści"),
    ("dopisanie karty",
     lambda tp: _fits(tp / "f.fits"),
     [writeback.WriteOp("OBSERVER", "add", "Zdzin", "str")], "add"),
    ("wartość liczbowa",
     lambda tp: _fits(tp / "g.fits", extra=[("FOCALLEN", 800)]),
     [writeback.WriteOp("FOCALLEN", "set", "789", "int")], "int"),
])
def test_fits_niekwalifikujacy_sie_spada_przed_zapisem(tmp_path, opis, plik, ops, fragment):
    """Spadek (`Fallback`) zapada PRZED dziennikiem i zapisem - plik i baza nietknięte."""
    p = plik(tmp_path)
    przed = p.read_bytes()
    res = writeback.write_changes_inplace(str(p), ops, _hash(p), journal=_NieWolno())
    assert isinstance(res, writeback.Fallback) and fragment in res.reason, (opis, res)
    assert p.read_bytes() == przed


def test_twarde_dowiazanie_widzi_nowy_naglowek(tmp_path):
    """Sedno O5: `os.replace` zrywa twarde dowiązanie projekcji `_WBPP`; zapis w miejscu - nie."""
    p = _fits(tmp_path / "h.fits")
    link = tmp_path / "_WBPP" / "h.fits"
    link.parent.mkdir()
    os.link(p, link)
    ino = os.stat(p).st_ino
    assert writeback.write_changes_inplace(str(p), _op(), _hash(p)).status == "applied"
    assert os.stat(p).st_ino == ino == os.stat(link).st_ino
    assert fits.getheader(str(link))["OBJECT"] == "NGC 6992"
    assert link.read_bytes() == p.read_bytes()


def test_weryfikacja_lapie_zmiane_danych(tmp_path, monkeypatch):
    """Próbka danych jest częścią weryfikacji: bajt danych zmieniony między zapisem a odczytem
    kontrolnym → 'failed' z backupem, faza `unverified`."""
    p = _fits(tmp_path / "i.fits")
    prawdziwy_fsync = os.fsync

    def _fsync_i_psuj(fd):
        # Pod blokadą nikt inny nie pisze - usterkę symulujemy NASZYM deskryptorem.
        prawdziwy_fsync(fd)
        os.lseek(fd, 2880, os.SEEK_SET)
        b = os.read(fd, 1)
        os.lseek(fd, 2880, os.SEEK_SET)
        os.write(fd, bytes([b[0] ^ 0xFF]))
    monkeypatch.setattr(writeback.os, "fsync", _fsync_i_psuj)
    dz = _Dziennik()
    res = writeback.write_changes_inplace(str(p), _op(), _hash(p), journal=dz)
    assert res.status == "failed" and "próbka danych" in res.reason and "klienta" in res.reason
    assert res.in_place and res.backup_text is not None and dz.fazy == ["unverified"]


def test_weryfikacja_lapie_inny_naglowek(tmp_path, monkeypatch):
    p = _fits(tmp_path / "j.fits")
    monkeypatch.setattr(writeback, "_post_hash", lambda path: "0" * 40)
    res = writeback.write_changes_inplace(str(p), _op(), _hash(p))
    assert res.status == "failed" and "header_hash" in res.reason and res.in_place
    assert fits.getheader(str(p))["OBJECT"] == "NGC 6992"      # plik ZMIENIONY - to nie rollback


def test_blokada_odcina_innych_piszacych_a_czytac_wolno(tmp_path):
    """Z2: pod `_exclusive` drugi pisarz nie otworzy pliku do zapisu, nie podmieni go ani nie usunie,
    a odczyt (astropy, `open("rb")`) działa."""
    p = _fits(tmp_path / "k.fits")
    obcy = _fits(tmp_path / "obcy.fits", seed=9)
    with writeback._exclusive(str(p)):
        with pytest.raises(PermissionError):
            open(p, "r+b")
        with pytest.raises(PermissionError):
            os.replace(obcy, p)
        with pytest.raises(PermissionError):
            os.remove(p)
        assert fits.getheader(str(p))["OBJECT"] == "NGC6992"
        assert p.read_bytes()[:6] == b"SIMPLE"
    with open(p, "r+b"):                                       # po zwolnieniu - znowu wolno
        pass


def test_blokada_ponawia_przy_bledzie_wspoldzielenia_i_poddaje_sie(tmp_path, monkeypatch):
    """Z10: plik trzymany do zapisu przez kogoś innego → kilka prób z przerwą, potem 'failed' bez
    zapisu i bez dziennika; gdy tamten puści w trakcie przerw - zapis przechodzi."""
    p = _fits(tmp_path / "r.fits")
    przed = p.read_bytes()
    pauzy = []
    monkeypatch.setattr(writeback.time, "sleep", lambda s: pauzy.append(s))
    with open(p, "r+b"):
        res = writeback.write_changes_inplace(str(p), _op(), _hash(p), journal=_NieWolno())
    assert res.status == "failed" and "WinError 32" in res.reason
    assert pauzy == list(writeback._LOCK_RETRY_DELAYS) and p.read_bytes() == przed

    trzymany = open(p, "r+b")
    monkeypatch.setattr(writeback.time, "sleep", lambda s: trzymany.close())
    assert writeback.write_changes_inplace(str(p), _op(), _hash(p)).status == "applied"


def test_blad_fdopen_zwalnia_deskryptor_i_blokade(tmp_path, monkeypatch):
    """Z14: wyjątek przy budowie obiektu pliku nie zostawia uchwytu (ani blokady) otwartego."""
    p = _fits(tmp_path / "fd.fits")

    def _pada(*a, **kw):
        raise MemoryError("symulacja")
    monkeypatch.setattr(writeback.os, "fdopen", _pada)
    res = writeback.write_changes_inplace(str(p), _op(), _hash(p), journal=_NieWolno())
    assert res.status == "failed" and "MemoryError" in res.reason
    monkeypatch.undo()
    with open(p, "r+b"):                                       # blokada zwolniona
        pass


def test_blad_zamkniecia_zachowuje_wynik_z_backupem(tmp_path, monkeypatch):
    """Z15: `close()` rzuca po zapisie - wynik z backupem i flagą mutacji przeżywa, a błąd zamknięcia
    dopisuje się do powodu (dawniej: 'failed' bez backupu, jakby zapisu nie było)."""
    p = _fits(tmp_path / "cl.fits")
    prawdziwy = writeback._exclusive

    import contextlib

    @contextlib.contextmanager
    def _zamkniecie_pada(path):
        with prawdziwy(path) as fh:
            yield fh
        raise OSError(64, "zerwany udział przy zamknięciu")
    monkeypatch.setattr(writeback, "_exclusive", _zamkniecie_pada)
    res = writeback.write_changes_inplace(str(p), _op(), _hash(p))
    assert res.status == "applied" and res.in_place and res.backup_text is not None
    assert "zamknięcie uchwytu padło" in res.reason
    assert fits.getheader(str(p))["OBJECT"] == "NGC 6992"


def test_suma_kontrolna_fits_to_odmowa_nie_spadek(tmp_path):
    """Z5: FITS z CHECKSUM/DATASUM → 'blocked' z powodem, także w commit(inplace=True)."""
    p = tmp_path / "sum.fits"
    hdu = fits.PrimaryHDU(data=np.zeros((4, 4), dtype=np.int16))
    hdu.header["IMAGETYP"] = "Light"
    hdu.header["OBJECT"] = ("NGC6992", KOMENTARZ)
    hdu.writeto(p, checksum=True)
    przed = p.read_bytes()
    res = writeback.write_changes_inplace(str(p), _op(), _hash(p), journal=_NieWolno())
    assert res.status == "blocked" and "CHECKSUM" in res.reason
    con, _ = _baza_z_plikiem(tmp_path, p)
    wynik = writeback.commit(con, "R", now=NOW, inplace=True)
    assert len(wynik.blocked) == 1 and not wynik.applied and p.read_bytes() == przed
    assert not _operacje(con)
    con.close()


# ============================================================ PISARZ XISF W MIEJSCU


def test_xisf_w_rezerwie_w_miejscu(tmp_path):
    """Łata XML-a w rezerwie przed pierwszym załącznikiem: pole długości nagłówka poprawne,
    pozycja i bajty załącznika bez zmian, komentarz karty zostaje, `st_ino` bez zmian."""
    p = _xisf(tmp_path / "a.xisf")
    przed = p.read_bytes()
    ino = os.stat(p).st_ino
    meta = scan.read_xisf_meta_full(str(p))
    res = writeback.write_changes_inplace(str(p), _op(), meta.header_hash)
    assert res.status == "applied" and res.in_place, res
    po = scan.read_xisf_meta_full(str(p))
    assert struct.unpack("<I", p.read_bytes()[8:12])[0] == len(po.xml_bytes) == len(meta.xml_bytes) + 1
    assert po.first_attachment == meta.first_attachment and po.image_span == meta.image_span
    assert p.read_bytes()[meta.first_attachment:] == przed[meta.first_attachment:]
    karta = next(c for c in po.cards if c.keyword == "OBJECT")
    assert (karta.value_raw, karta.comment) == ("NGC 6992", "nazwa obiektu")
    assert os.stat(p).st_ino == ino and len(p.read_bytes()) == len(przed)


def test_xisf_bez_rezerwy_odmawia_bez_zapisu(tmp_path):
    """Brak rezerwy odmawia w OBU drogach tym samym zdaniem - spadku nie ma, jest 'blocked'."""
    p = _xisf(tmp_path / "b.xisf", pad=0)
    przed = p.read_bytes()
    h = scan.read_xisf_meta_full(str(p)).header_hash
    res = writeback.write_changes_inplace(str(p), _op(), h, journal=_NieWolno())
    assert res.status == "blocked" and "nie mieści się" in res.reason
    assert p.read_bytes() == przed
    atomowo = writeback.write_changes(str(p), _op(), h)
    assert atomowo.status == "blocked" and atomowo.reason == res.reason


def test_xisf_zly_hash_blokuje(tmp_path):
    p = _xisf(tmp_path / "c.xisf")
    przed = p.read_bytes()
    res = writeback.write_changes_inplace(str(p), _op(), "nie-ten", journal=_NieWolno())
    assert res.status == "blocked" and res.reason == "header_hash mismatch"
    assert p.read_bytes() == przed


# ============================================================ ORKIESTRACJA: commit / undo w miejscu


@pytest.mark.parametrize("fmt", ["fits", "xisf"])
def test_commit_i_undo_w_miejscu_bajt_w_bajt_z_faza_operacji(tmp_path, fmt):
    """Commit w miejscu → operacja `commit` w fazie `synced`; undo W MIEJSCU (ten sam inode) →
    operacja `undo` `synced`, plik bajt w bajt sprzed commitu (XISF z niezerowym wypełnieniem - Z7),
    baza zsynchronizowana; drugie undo rozpoznaje „już cofnięte" z FAZY (Z13)."""
    p = (_fits(tmp_path / "a.fits") if fmt == "fits"
         else _xisf(tmp_path / "a.xisf", wypelnienie=b"\x20"))
    przed = p.read_bytes()
    ino = os.stat(p).st_ino
    con, loc = _baza_z_plikiem(tmp_path, p)
    sha = con.execute("SELECT sha1_data FROM frame WHERE id=?", (loc["frame_id"],)).fetchone()[0]

    res = writeback.commit(con, "R", now=NOW, inplace=True)
    assert len(res.applied) == 1 and res.in_place == res.applied and not res.failed
    assert [tuple(o)[1:] for o in _operacje(con)] == [("commit", "synced")]
    assert con.execute("SELECT object_raw FROM header WHERE frame_id=?",
                       (loc["frame_id"],)).fetchone()[0] == "NGC 6992"
    assert con.execute("SELECT count(*) FROM frame").fetchone()[0] == 1
    assert con.execute("SELECT sha1_data FROM frame").fetchone()[0] == sha

    ures = writeback.undo(con, res.commit_id, now=NOW)
    assert len(ures.restored) == 1 and not ures.failed, ures
    assert p.read_bytes() == przed and os.stat(p).st_ino == ino
    assert [tuple(o)[1:] for o in _operacje(con)] == [("commit", "synced"), ("undo", "synced")]
    assert _loc(con, p)["header_hash"] == loc["header_hash"]
    u2 = writeback.undo(con, res.commit_id, now=NOW)
    assert len(u2.blocked) == 1 and "już cofnięte" in u2.blocked[0].reason
    con.close()


def test_commit_porazka_dziennika_nie_rusza_pliku(tmp_path, monkeypatch):
    p = _fits(tmp_path / "b.fits")
    przed = p.read_bytes()
    con, loc = _baza_z_plikiem(tmp_path, p)

    def _pada(*a, **kw):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(writeback.repo, "begin_inplace_commit", _pada)
    res = writeback.commit(con, "R", now=NOW, inplace=True)
    assert len(res.failed) == 1 and "NIE powstał" in res.failed[0].reason
    assert p.read_bytes() == przed and not _operacje(con)
    assert con.execute("SELECT count(*) FROM header_backups").fetchone()[0] == 0
    con.close()


def test_backup_i_operacja_w_jednej_transakcji(tmp_path, monkeypatch):
    """Operacja nie wchodzi bez backupu ani backup bez operacji: wyjątek przy INSERT operacji
    wycofuje też backup i wiersz commitu (jedna transakcja)."""
    p = _fits(tmp_path / "t.fits")
    przed = p.read_bytes()
    con, loc = _baza_z_plikiem(tmp_path, p)
    monkeypatch.setattr(repo, "_INSERT_INPLACE_OP", "INSERT INTO nie_ma_takiej(x) VALUES (?)")
    res = writeback.commit(con, "R", now=NOW, inplace=True)
    assert len(res.failed) == 1 and p.read_bytes() == przed
    assert con.execute("SELECT count(*) FROM header_backups").fetchone()[0] == 0
    assert con.execute("SELECT count(*) FROM commits").fetchone()[0] == 0
    con.close()


def test_przerwany_zapis_izoluje_lokacje_a_odzysk_ja_zwalnia(tmp_path, monkeypatch):
    """Q8/warunek 7: zapis w miejscu przerwany (fsync rzuca) → operacja `unverified`, klatka w wierszu
    Porządków, skan drzewa POMIJA plik (nawet przy wyłączonej bramie), undo odsyła do odzysku.
    `recover_torn` przywraca plik bajt w bajt, zdejmuje izolację i synchronizuje bazę."""
    kat = tmp_path / "arch"
    kat.mkdir()
    p = _fits(kat / "a.fits")
    przed = p.read_bytes()
    con, loc = _baza_z_plikiem(tmp_path, p)
    _psuj_fsync(monkeypatch)
    res = writeback.commit(con, "R", now=NOW, inplace=True)
    monkeypatch.undo()
    assert len(res.failed) == 1 and "IZOLOWANA" in res.failed[0].reason
    (op_id, kind, faza), = [tuple(o) for o in _operacje(con)]
    assert (kind, faza) == ("commit", "unverified")
    assert queries.torn_write_frame_ids(con) == {loc["frame_id"]}
    assert queries.tasks_state(con)["torn_write_frames"] == 1

    for vol in ("V", "?"):                                     # z bramą i bez niej
        s = scan.scan_tree(con, str(kat), volume=vol, now=NOW)
        assert s.isolated == 1 and s.isolated_paths == [str(p)]
    assert con.execute("SELECT count(*) FROM location").fetchone()[0] == 1

    u = writeback.undo(con, res.commit_id, now=NOW)
    assert len(u.failed) == 1 and f"recover_torn({op_id})" in u.failed[0].reason

    wynik = writeback.recover_torn(con, op_id, now=NOW)
    assert wynik.status == "restored", wynik
    assert p.read_bytes() == przed and queries.torn_write_frame_ids(con) == set()
    assert tuple(_operacje(con)[0])[2] == "recovered"
    assert _loc(con, p)["header_hash"] == loc["header_hash"]
    con.close()


def test_zwolnienie_reka_zdejmuje_izolacje_ze_zdarzeniem(tmp_path, monkeypatch):
    p = _fits(tmp_path / "z.fits")
    con, loc = _baza_z_plikiem(tmp_path, p)
    _psuj_fsync(monkeypatch)
    writeback.commit(con, "R", now=NOW, inplace=True)
    monkeypatch.undo()
    op_id = _operacje(con)[0]["id"]
    repo.release_inplace_op(con, op_id=op_id, now=NOW, reason="przywrócone z pełnej kopii")
    assert queries.torn_write_frame_ids(con) == set() and not scan._isolated(con, str(p))
    ev = con.execute("SELECT reason FROM event WHERE verb='location.writeback_released'").fetchone()
    assert ev["reason"] == "przywrócone z pełnej kopii"
    with pytest.raises(ValueError):
        repo.release_inplace_op(con, op_id=op_id, now=NOW, reason="drugi raz")
    con.close()


def test_commit_rozjazd_sha1_data_nie_rozdwaja_klatki(tmp_path, monkeypatch):
    p = _fits(tmp_path / "d.fits")
    con, loc = _baza_z_plikiem(tmp_path, p)
    prawdziwy = scan.scan_file
    monkeypatch.setattr(writeback.scan, "scan_file",
                        lambda path, **kw: dataclasses.replace(prawdziwy(path, **kw),
                                                               sha1_data="f" * 40))
    res = writeback.commit(con, "R", now=NOW, inplace=True)
    assert len(res.failed) == 1 and "sha1_data" in res.failed[0].reason
    assert con.execute("SELECT count(*) FROM frame").fetchone()[0] == 1
    con.close()


def test_commit_awaria_resyncu_nie_zatrzymuje_wsadu(tmp_path, monkeypatch):
    con = db.open_db(str(tmp_path / "h.db"))
    pierwszy = _fits(tmp_path / "p1.fits", seed=1)
    drugi = _fits(tmp_path / "p2.fits", seed=2)
    for p in (pierwszy, drugi):
        _scan_in(con, p)
        loc = _loc(con, p)
        _stage(con, "R", loc["id"], "NGC 6992", loc["header_hash"])
    prawdziwy = scan.scan_file

    def _czkawka(path, **kw):
        if path == str(pierwszy):
            raise OSError(64, "The specified network name is no longer available")
        return prawdziwy(path, **kw)
    monkeypatch.setattr(writeback.scan, "scan_file", _czkawka)
    res = writeback.commit(con, "R", now=NOW, inplace=True)
    assert [f.path for f in res.failed] == [str(pierwszy)] and "re-sync padł" in res.failed[0].reason
    assert [f.path for f in res.applied] == [str(drugi)]
    fazy = {r["location_id"]: r["phase"] for r in con.execute(
        "SELECT location_id, phase FROM inplace_op")}
    assert fazy == {_loc(con, pierwszy)["id"]: "written", _loc(con, drugi)["id"]: "synced"}
    con.close()


def test_spadek_idzie_droga_atomowa_albo_blokuje_w_trybie_pilotazu(tmp_path):
    """Warunek 6: `fallback=False` - plik, który nie mieści się w miejscu, → 'blocked', zero zapisu;
    domyślnie spadek na drogę atomową z powodem w wyniku. Spadek z powodu zastanego komentarza,
    który nie zmieści się przy nowej wartości, kończy się na drodze atomowej odmową (AR-7) - tam
    astropy uciąłby komentarz po cichu."""
    p = _fits(tmp_path / "e.fits", extra=[("OBJECT", "NGC6992")])      # dwie karty → spadek
    przed = p.read_bytes()
    con = db.open_db(str(tmp_path / "h.db"))
    _scan_in(con, p)
    loc = _loc(con, p)
    _stage(con, "R", loc["id"], "V" * 20, loc["header_hash"])
    res = writeback.commit(con, "R", now=NOW, inplace=True, fallback=False)
    assert len(res.blocked) == 1 and "tryb bez spadku" in res.blocked[0].reason
    assert p.read_bytes() == przed

    _stage(con, "R2", loc["id"], "V" * 20, loc["header_hash"])
    res2 = writeback.commit(con, "R2", now=NOW, inplace=True)
    assert len(res2.applied) == 1 and not res2.in_place
    assert res2.applied[0].reason.startswith("droga dotychczasowa: ")
    hdr = fits.getheader(str(p))
    assert hdr["OBJECT"] == "V" * 20 and hdr.comments["OBJECT"] == KOMENTARZ

    q = _fits(tmp_path / "e2.fits", obj="M31", comment="k" * 47, seed=1)
    przed_q = q.read_bytes()
    _scan_in(con, q)
    loc_q = _loc(con, q)
    _stage(con, "R3", loc_q["id"], "V" * 20, loc_q["header_hash"])
    res3 = writeback.commit(con, "R3", now=NOW, inplace=True)
    assert len(res3.blocked) == 1 and "ucięłaby zastany komentarz" in res3.blocked[0].reason
    assert q.read_bytes() == przed_q
    con.close()


def _stary_commit(con, path, value, run_id="STARY"):
    """Commit ŚCIEŻKĄ SPRZED 2026-09-26 (HEAD 999f328, `writeback.write_changes` + `commit`), odtworzony
    dosłownie: backup = `hdr.tostring()` (tekst), astropy `writeto` do pliku tymczasowego,
    `os.replace`, a backup i commit wstawiane PO podmianie. Tak wyglądają commity w żywej bazie."""
    with fits.open(str(path), mode="readonly", memmap=False) as hdul:
        hdr = hdul[0].header
        backup_text = hdr.tostring()
        hdr["OBJECT"] = value
        fd, tmp = tempfile.mkstemp(suffix=".tmp", dir=str(Path(path).parent))
        os.close(fd)
        hdul.writeto(tmp, overwrite=True)
    os.replace(tmp, str(path))
    post = scan.read_fits_meta(str(path)).header_hash
    cid = repo.insert_commit(con, run_id=run_id, now=NOW, summary=f"run {run_id}")
    lid = _loc(con, path)["id"]
    repo.insert_header_backup(con, commit_id=cid, location_id=lid, hdu_index=0,
                              header_text=backup_text, post_hash=post)
    writeback._resync(con, str(path), "V", now=NOW)
    return cid


def test_undo_starego_backupu_tekstowego_idzie_atomowo(tmp_path):
    """Z12: commit sprzed zmiany (backup tekstowy, inny inode po `os.replace`) cofa się WYŁĄCZNIE
    drogą atomową - bez operacji `undo` w dzienniku, bo w miejscu nie byłoby czym odzyskać przerwy."""
    p = _fits(tmp_path / "s.fits")
    con = db.open_db(str(tmp_path / "h.db"))
    _scan_in(con, p)
    cid = _stary_commit(con, p, "NGC 6992")
    assert not writeback.RegionBackup.decode(
        con.execute("SELECT header_text FROM header_backups").fetchone()[0])
    ino = os.stat(p).st_ino
    ures = writeback.undo(con, cid, now=NOW)
    assert len(ures.restored) == 1 and not _operacje(con), ures
    assert fits.getheader(str(p))["OBJECT"] == "NGC6992"
    assert os.stat(p).st_ino != ino                            # droga atomowa: nowy plik
    assert len(writeback.undo(con, cid, now=NOW).blocked) == 1
    con.close()


def test_undo_commitu_atomowego_idzie_atomowo(tmp_path):
    """Z12: commit atomowy (nowy kod, koperta) też cofa się atomowo - nie ma operacji `commit`."""
    p = _fits(tmp_path / "f.fits")
    con, loc = _baza_z_plikiem(tmp_path, p)
    res = writeback.commit(con, "R", now=NOW)
    ures = writeback.undo(con, res.commit_id, now=NOW)
    assert len(ures.restored) == 1 and not _operacje(con)
    assert fits.getheader(str(p))["OBJECT"] == "NGC6992"
    con.close()


def test_undo_po_awarii_resyncu_konczy_sama_synchronizacja(tmp_path, monkeypatch):
    """Z4/Z13: undo w miejscu przywraca nagłówek, re-sync pada → operacja `undo` w fazie `written`,
    'failed'. Ponowne undo robi SAM re-sync (faza → `synced`); trzecie → 'blocked' (już cofnięte)."""
    p = _fits(tmp_path / "u.fits")
    przed = p.read_bytes()
    con, loc = _baza_z_plikiem(tmp_path, p)
    res = writeback.commit(con, "R", now=NOW, inplace=True)
    prawdziwy = scan.scan_file
    monkeypatch.setattr(writeback.scan, "scan_file",
                        lambda path, **kw: (_ for _ in ()).throw(OSError(64, "zerwany udział")))
    u1 = writeback.undo(con, res.commit_id, now=NOW)
    assert len(u1.failed) == 1 and "ponowne undo" in u1.failed[0].reason
    assert p.read_bytes() == przed and _operacje(con)[-1]["phase"] == "written"
    monkeypatch.setattr(writeback.scan, "scan_file", prawdziwy)
    u2 = writeback.undo(con, res.commit_id, now=NOW)
    assert len(u2.restored) == 1 and "dokończono synchronizację" in u2.restored[0].reason
    assert _loc(con, p)["header_hash"] == loc["header_hash"]
    assert len(writeback.undo(con, res.commit_id, now=NOW).blocked) == 1
    con.close()


def test_resync_commitu_i_undo_padly_ponowienie_robi_synchronizacje(tmp_path, monkeypatch):
    """Z13, przypadek 2 (astra): commit bez udanego re-syncu (baza ma hash A sprzed commitu). Dawniej
    undo przywracało A obok operacji commitu w fazie `written`, która zostawała tak na zawsze;
    od 2026-09-27 `written` IZOLUJE lokację, więc undo najpierw DOKAŃCZA commit (kontrola danych
    + re-sync), a dopiero potem cofa. Re-sync nadal pada → undo 'failed', plik nietknięty (stan po
    commicie), żadnej operacji cofnięcia. Rozpoznanie po `header_hash` („baza ma A") nie może dać
    „już cofnięte": ponowienie dokańcza commit i cofa - obie operacje `synced`, baza znów ma A."""
    p = _fits(tmp_path / "v.fits")
    przed = p.read_bytes()
    con, loc = _baza_z_plikiem(tmp_path, p)
    prawdziwy = scan.scan_file
    monkeypatch.setattr(writeback.scan, "scan_file",
                        lambda path, **kw: (_ for _ in ()).throw(OSError(64, "zerwany udział")))
    res = writeback.commit(con, "R", now=NOW, inplace=True)
    assert len(res.failed) == 1 and "finish_inplace" in res.failed[0].reason
    po_commicie = p.read_bytes()
    u1 = writeback.undo(con, res.commit_id, now=NOW)
    assert len(u1.failed) == 1 and "commit nie jest dokończony" in u1.failed[0].reason
    assert p.read_bytes() == po_commicie and [o["phase"] for o in _operacje(con)] == ["written"]
    assert _loc(con, p)["header_hash"] == loc["header_hash"]        # baza wciąż ma hash A
    monkeypatch.setattr(writeback.scan, "scan_file", prawdziwy)
    u2 = writeback.undo(con, res.commit_id, now=NOW)
    assert len(u2.restored) == 1 and not u2.failed, u2
    assert [o["phase"] for o in _operacje(con)] == ["synced", "synced"]
    assert p.read_bytes() == przed and _loc(con, p)["header_hash"] == loc["header_hash"]
    con.close()


def test_przerwane_undo_xisf_z_wypelnieniem_przez_odzysk(tmp_path, monkeypatch):
    """Z13, przypadek 1 (astra): undo XISF przerwane - hash XML-a mógłby się już zgadzać, a region
    (wypełnienie) nie. Undo nie rozpoznaje „przywrócone" po hashu: operacja otwarta odsyła do
    odzysku; odzysk wraca do stanu po commicie, kolejne undo odtwarza CAŁY region z wypełnieniem."""
    p = _xisf(tmp_path / "w.xisf", wypelnienie=b"\x20")
    przed = p.read_bytes()
    con, loc = _baza_z_plikiem(tmp_path, p)
    res = writeback.commit(con, "R", now=NOW, inplace=True)
    po_commicie = p.read_bytes()
    _psuj_fsync(monkeypatch)
    u1 = writeback.undo(con, res.commit_id, now=NOW)
    monkeypatch.undo()
    assert len(u1.failed) == 1 and "IZOLOWANA" in u1.failed[0].reason
    op_u = _operacje(con)[-1]
    assert (op_u["kind"], op_u["phase"]) == ("undo", "unverified")
    u2 = writeback.undo(con, res.commit_id, now=NOW)
    assert len(u2.failed) == 1 and f"recover_torn({op_u['id']})" in u2.failed[0].reason
    assert writeback.recover_torn(con, op_u["id"], now=NOW).status == "restored"
    assert p.read_bytes() == po_commicie
    u3 = writeback.undo(con, res.commit_id, now=NOW)
    assert len(u3.restored) == 1 and p.read_bytes() == przed
    con.close()


# ============================================================ ODZYSK (astra Z11)


def _otwarta_operacja(tmp_path, monkeypatch, plik):
    """Commit w miejscu z weryfikacją rozjechaną → operacja `unverified` (region zapisany cały)."""
    przed = plik.read_bytes()
    con, loc = _baza_z_plikiem(tmp_path, plik)
    _psuj_fsync(monkeypatch)
    writeback.commit(con, "R", now=NOW, inplace=True)
    monkeypatch.undo()
    op = con.execute("SELECT * FROM inplace_op").fetchone()
    return con, op, przed


def test_odzysk_stanu_posredniego_bajt_w_bajt(tmp_path, monkeypatch):
    """Rozdarcie = część zakresu zapisu stara, część nowa. Odzysk bez parsowania przywraca plik."""
    p = _fits(tmp_path / "t.fits")
    con, op, przed = _otwarta_operacja(tmp_path, monkeypatch, p)
    a, b = op["write_start"], op["write_end"]
    dane = bytearray(p.read_bytes())
    dane[a:(a + b) // 2] = przed[a:(a + b) // 2]             # pół zakresu wróciło do starego
    p.write_bytes(bytes(dane))
    assert writeback.recover_torn(con, op["id"], now=NOW).status == "restored"
    assert p.read_bytes() == przed
    con.close()


def test_odzysk_odmawia_po_przebudowie_pliku_kontrprzyklad_astry(tmp_path, monkeypatch):
    """Z11 DOSŁOWNIE: A = nagłówek 5760 B + 5760 B danych zer; B = poprawna przebudowa W MIEJSCU tego
    samego pliku: nagłówek 2880 B + 8640 B danych (pierwsze 2880 B niezerowe). Ten sam rozmiar
    (11 520 B), ten sam inode, wszystkie trzy próbki liczone po starym regionie równe - dawny odzysk
    przywracał stary region i kasował 2880 B pikseli B. Teraz: region nie jest stanem pośrednim
    operacji → odmowa, plik B nietknięty."""
    a_plik = tmp_path / "ab.fits"
    extra = [(f"K{i:03d}", i) for i in range(40)]              # nagłówek 2 bloki
    _fits(a_plik, extra=extra, dane=np.zeros((2880,), dtype=np.int16))
    assert len(a_plik.read_bytes()) == 11520
    con, op, przed = _otwarta_operacja(tmp_path, monkeypatch, a_plik)
    assert op["region_length"] == 5760

    b_plik = tmp_path / "b_wzor.fits"
    dane_b = np.zeros((4320,), dtype=np.int16)
    dane_b[:1440] = np.arange(1, 1441, dtype=np.int16)
    _fits(b_plik, dane=dane_b)
    b = b_plik.read_bytes()
    assert len(b) == 11520
    ino = os.stat(a_plik).st_ino
    with open(a_plik, "r+b") as fh:                            # przebudowa W MIEJSCU (ten sam inode)
        fh.write(b)
    assert os.stat(a_plik).st_ino == ino
    spec = writeback._spec_z_operacji(op)
    with open(a_plik, "rb") as fh:                             # próbki starego regionu - równe
        rozmiar = os.fstat(fh.fileno()).st_size
        proba_b = writeback._probe(fh, 0, 5760, rozmiar)
    with open(tmp_path / "a_przed.fits", "wb") as fh:
        fh.write(przed)
    with open(tmp_path / "a_przed.fits", "rb") as fh:
        proba_a = writeback._probe(fh, 0, 5760, rozmiar)
    assert (spec.file_size, proba_b[1:]) == (11520, proba_a[1:])

    wynik = writeback.recover_torn(con, op["id"], now=NOW)
    assert wynik.status == "blocked" and "to nie jest rozdarcie tej operacji" in wynik.reason
    assert a_plik.read_bytes() == b                            # piksele B całe
    con.close()


def test_odzysk_odmawia_obcej_wartosci_w_zakresie_zapisu(tmp_path, monkeypatch):
    """Z11: późniejsza legalna zmiana samego OBJECT (ten sam rozmiar, inode, próbki) - bajt
    w zakresie, który nie jest ani stary, ani nowy → odmowa."""
    p = _fits(tmp_path / "o.fits")
    con, op, _ = _otwarta_operacja(tmp_path, monkeypatch, p)
    dane = bytearray(p.read_bytes())
    slot = dane.index(b"OBJECT  = ")
    dane[slot:slot + 80] = fits.Card("OBJECT", "NGC 7000", KOMENTARZ).image.encode("ascii")
    p.write_bytes(bytes(dane))
    po = p.read_bytes()
    wynik = writeback.recover_torn(con, op["id"], now=NOW)
    assert wynik.status == "blocked" and "obca zmiana" in wynik.reason and p.read_bytes() == po
    con.close()


def test_odzysk_nie_zalezy_od_probek_i_nie_dotyka_danych(tmp_path, monkeypatch):
    """Zmiana POZA próbkami (środek dużego pliku) nie jest dowodem ani przeciwdowodem rozdarcia:
    odzysk pisze wyłącznie zakres operacji, więc obca zmiana danych zostaje nietknięta."""
    p = _fits(tmp_path / "duzy.fits", dane=np.zeros((256 * 1024,), dtype=np.int16))
    con, op, przed = _otwarta_operacja(tmp_path, monkeypatch, p)
    srodek = len(przed) // 2
    dane = bytearray(p.read_bytes())
    dane[srodek] ^= 0xFF
    p.write_bytes(bytes(dane))
    assert writeback.recover_torn(con, op["id"], now=NOW).status in ("restored", "failed")
    po = p.read_bytes()
    assert po[:2880] == przed[:2880] and po[srodek] == dane[srodek]
    con.close()


def test_odzysk_tylko_dla_operacji_otwartej_i_tego_pliku(tmp_path, monkeypatch):
    """Operacja zamknięta → odmowa; inny rozmiar pliku → odmowa z instrukcją ręczną."""
    p = _fits(tmp_path / "zam.fits")
    con, loc = _baza_z_plikiem(tmp_path, p)
    writeback.commit(con, "R", now=NOW, inplace=True)
    op_id = _operacje(con)[0]["id"]
    w = writeback.recover_torn(con, op_id, now=NOW)
    assert w.status == "blocked" and "nie jest otwarta" in w.reason
    con.close()

    q = _fits(tmp_path / "roz.fits")
    con2, op, _ = _otwarta_operacja_w(tmp_path / "b", monkeypatch, q)
    with open(q, "ab") as fh:
        fh.write(b"\x00" * 2880)
    w2 = writeback.recover_torn(con2, op["id"], now=NOW)
    assert w2.status == "blocked" and "ręcznie" in w2.reason
    con2.close()


def _otwarta_operacja_w(katalog, monkeypatch, plik):
    katalog.mkdir(exist_ok=True)
    return _otwarta_operacja(katalog, monkeypatch, plik)


# ============================================================ SZWY PISARZA (astra, 2026-09-27)
# Kontrola danych całego pliku, izolacja do `synced`, generacja skanu, faza pod blokadą,
# nieutrwalona faza, ponowione cofnięcie i jedna bramka izolacji przed każdą mutacją. Każdy test
# bez naprawy pada.


def _fits_dwa_hdu(path):
    """FITS z DRUGIM HDU daleko od próbek pisarza: dane główne 128 KiB, rozszerzenie 128 KiB.
    Zwraca `(ścieżka, offset danych drugiego HDU)`."""
    prim = fits.PrimaryHDU(data=(np.arange(256 * 256) % 3000).astype(np.int16).reshape(256, 256))
    prim.header["IMAGETYP"] = "Light"
    prim.header["OBJECT"] = ("NGC6992", KOMENTARZ)
    ext = fits.ImageHDU(data=np.full((256, 256), 3, dtype=np.int16), name="DRUGI")
    fits.HDUList([prim, ext]).writeto(path, overwrite=True)
    with fits.open(str(path)) as hdul:
        return path, hdul.fileinfo(1)["datLoc"]


def _xisf_dwa_obrazy(path, pad=64):
    """XISF z kartami pod pierwszym obrazem i DRUGIM obrazem 200 KiB (bez kart). Zwraca
    `(ścieżka, offset bajtu drugiego obrazu poza próbkami pisarza)`."""
    p1, p2 = b"\x07" * 32, bytes(range(256)) * 800

    def body(s1, s2):
        kw = ('<FITSKeyword name="IMAGETYP" value="\'Light\'" comment=""/>'
              '<FITSKeyword name="OBJECT" value="\'NGC6992\'" comment="nazwa obiektu"/>')
        return ('<?xml version="1.0" encoding="UTF-8"?>'
                '<xisf version="1.0" xmlns="http://www.pixinsight.com/xisf">'
                f'<Image geometry="4:4:1" sampleFormat="UInt16" '
                f'location="attachment:{s1:08d}:{len(p1)}">{kw}</Image>'
                f'<Image id="drugi" geometry="320:320:1" sampleFormat="UInt16" '
                f'location="attachment:{s2:08d}:{len(p2)}"/></xisf>').encode("utf-8")
    s1 = scan.XISF_XML_OFFSET + len(body(0, 0)) + pad
    xml = body(s1, s1 + len(p1))
    with open(path, "wb") as fh:
        fh.write(b"XISF0100" + struct.pack("<I", len(xml)) + b"\x00" * 4 + xml
                 + b"\x00" * pad + p1 + p2)
    return path, s1 + len(p1) + 100 * 1024


def _psuj_bajt_przy_fsync(monkeypatch, offset):
    """Usterka zapisu poza regionem nagłówka: po `fsync` bajt pod `offset` (poza próbkami pisarza)
    zmienia się NASZYM deskryptorem - pod blokadą nikt inny nie pisze."""
    prawdziwy = os.fsync

    def _fsync(fd):
        prawdziwy(fd)
        os.lseek(fd, offset, os.SEEK_SET)
        b = os.read(fd, 1)
        os.lseek(fd, offset, os.SEEK_SET)
        os.write(fd, bytes([b[0] ^ 0xFF]))
    monkeypatch.setattr(writeback.os, "fsync", _fsync)


def _zerwany_udzial(monkeypatch):
    """Re-sync pada: pełny odczyt pliku rzuca (czkawka SMB)."""
    monkeypatch.setattr(writeback.scan, "scan_file",
                        lambda path, **kw: (_ for _ in ()).throw(OSError(64, "zerwany udział")))


@pytest.mark.parametrize("fmt", ["fits", "xisf"])
def test_kontrola_danych_lapie_bajt_poza_naglowkiem_i_probkami(tmp_path, monkeypatch, fmt):
    """Bajt drugiego HDU FITS / drugiego obrazu XISF zmieniony przy zapisie, poza trzema próbkami
    i poza `sha1_data` (pierwsze HDU / pierwszy obraz). Dawniej commit zgłaszał 'applied'. Teraz
    kontrola danych (sha1 pliku z podstawionym starym regionem != kotwica bazy) → 'failed', baza
    NIE wciąga pliku, operacja zostaje `written` - lokacja izolowana."""
    p, zly = (_fits_dwa_hdu(tmp_path / "d.fits") if fmt == "fits"
              else _xisf_dwa_obrazy(tmp_path / "d.xisf"))
    con, loc = _baza_z_plikiem(tmp_path, p)
    _psuj_bajt_przy_fsync(monkeypatch, zly)
    res = writeback.commit(con, "R", now=NOW, inplace=True)
    monkeypatch.undo()
    assert not res.applied and len(res.failed) == 1, res
    assert "POZA regionem" in res.failed[0].reason
    assert [o["phase"] for o in _operacje(con)] == ["written"] and scan._isolated(con, str(p))
    assert _loc(con, p)["header_hash"] == loc["header_hash"]         # baza nie wciągnęła pliku
    con.close()


def test_kontrola_danych_przy_cofnieciu_w_miejscu(tmp_path, monkeypatch):
    """To samo sprawdzenie dla undo w miejscu: region podstawiony = region wynikowy commitu,
    kotwica = `file_sha1` po commicie."""
    p, zly = _fits_dwa_hdu(tmp_path / "u.fits")
    con, loc = _baza_z_plikiem(tmp_path, p)
    res = writeback.commit(con, "R", now=NOW, inplace=True)
    assert len(res.in_place) == 1
    po_commicie = _loc(con, p)["header_hash"]
    _psuj_bajt_przy_fsync(monkeypatch, zly)
    u = writeback.undo(con, res.commit_id, now=NOW)
    monkeypatch.undo()
    assert not u.restored and len(u.failed) == 1 and "POZA regionem" in u.failed[0].reason
    assert [(o["kind"], o["phase"]) for o in _operacje(con)] == [("commit", "synced"),
                                                                 ("undo", "written")]
    assert _loc(con, p)["header_hash"] == po_commicie and scan._isolated(con, str(p))
    con.close()


def test_kontrola_danych_przy_odzysku(tmp_path, monkeypatch):
    """Odzysk rozdartego nagłówka: bajt poza regionem zmieniony przy zapisie odzysku, więc kontrola
    danych po odzysku NIE przechodzi. Dawniej operacja zostawała OTWARTA z jedynym wyjściem
    `release_inplace_op` (ponowienie powtarzało tę samą niezgodność). Teraz ta sama droga powrotu
    co z `written` (AR-17 (6)): stary nagłówek w miejscu, faza `recovered` z powodem, wpis
    stagingu 'failed', `location.mtime` NULL - lokacja wraca do pełnego skanu."""
    p, zly = _fits_dwa_hdu(tmp_path / "o.fits")
    con, op, przed = _otwarta_operacja(tmp_path, monkeypatch, p)
    _psuj_bajt_przy_fsync(monkeypatch, zly)
    w = writeback.recover_torn(con, op["id"], now=NOW)
    monkeypatch.undo()
    assert w.status == "restored" and "POZA regionem" in w.reason and "przeskanuj" in w.reason, w
    a, n = op["region_offset"], op["region_length"]
    assert p.read_bytes()[a:a + n] == przed[a:a + n]
    assert _operacje(con)[0]["phase"] == "recovered" and not scan._isolated(con, str(p))
    assert con.execute("SELECT mtime FROM location").fetchone()[0] is None
    (wpis,) = writeback.pending_for_run(con, "R")
    assert wpis["status"] == "failed" and "przeskanuj" in wpis["reason"]
    con.close()


def test_kotwica_pusta_liczona_pelnym_odczytem_przed_zapisem(tmp_path, monkeypatch):
    """`location.file_sha1` NULL → pisarz liczy kotwicę pełnym odczytem uchwytu PRZED pierwszym
    bajtem i odkłada ją do koperty backupu; kontrola danych działa tak samo (bajt poza nagłówkiem
    → 'failed'), a bez usterki commit przechodzi."""
    p, zly = _fits_dwa_hdu(tmp_path / "n.fits")
    przed = p.read_bytes()
    con, loc = _baza_z_plikiem(tmp_path, p)
    con.execute("UPDATE location SET file_sha1 = NULL WHERE id = ?", (loc["id"],))   # tylko test
    con.commit()
    _psuj_bajt_przy_fsync(monkeypatch, zly)
    res = writeback.commit(con, "R", now=NOW, inplace=True)
    monkeypatch.undo()
    assert len(res.failed) == 1 and "POZA regionem" in res.failed[0].reason
    env = writeback.RegionBackup.decode(
        con.execute("SELECT header_text FROM header_backups").fetchone()[0])
    import hashlib
    assert env.file_sha1 == hashlib.sha1(przed).hexdigest()

    q, _ = _fits_dwa_hdu(tmp_path / "n2.fits")
    con2 = db.open_db(str(tmp_path / "h2.db"))
    _scan_in(con2, q)
    l2 = _loc(con2, q)
    _stage(con2, "R", l2["id"], "NGC 6992", l2["header_hash"])
    con2.execute("UPDATE location SET file_sha1 = NULL WHERE id = ?", (l2["id"],))
    con2.commit()
    assert len(writeback.commit(con2, "R", now=NOW, inplace=True).in_place) == 1
    con.close()
    con2.close()


def test_kotwica_nieaktualna_blokuje_przed_zapisem(tmp_path):
    """Baza nie opisuje pliku (bajt drugiego HDU zmieniony po skanie, inny `mtime`) → kontrola
    danych po zapisie nie miałaby kotwicy: 'blocked' PRZED pierwszym bajtem, bez dziennika."""
    p, zly = _fits_dwa_hdu(tmp_path / "k.fits")
    con, loc = _baza_z_plikiem(tmp_path, p)
    dane = bytearray(p.read_bytes())
    dane[zly] ^= 0xFF
    p.write_bytes(bytes(dane))
    os.utime(p, (1_700_000_000, 1_700_000_000))
    res = writeback.commit(con, "R", now=NOW, inplace=True)
    assert len(res.blocked) == 1 and "od ostatniego skanu" in res.blocked[0].reason, res
    assert p.read_bytes() == bytes(dane) and not _operacje(con)
    con.close()


def test_izolacja_trwa_do_synced_a_finish_inplace_ja_zdejmuje(tmp_path, monkeypatch):
    """Re-sync commitu w miejscu padł → operacja `written` IZOLUJE lokację (dawniej izolacja znikała
    na `written`, a skan mógł przepiąć kopię). Skan pomija plik (z bramą i bez), odzysk odsyła do
    dokończenia, `finish_inplace` robi kontrolę danych i re-sync → `synced`, wpisy stagingu
    'applied', izolacja zdjęta; drugie dokończenie → 'blocked'."""
    kat = tmp_path / "arch"
    kat.mkdir()
    p = _fits(kat / "a.fits")
    con, loc = _baza_z_plikiem(tmp_path, p)
    prawdziwy = scan.scan_file
    _zerwany_udzial(monkeypatch)
    res = writeback.commit(con, "R", now=NOW, inplace=True)
    monkeypatch.setattr(writeback.scan, "scan_file", prawdziwy)
    (op_id, _, faza), = [tuple(o) for o in _operacje(con)]
    assert faza == "written" and f"finish_inplace({op_id})" in res.failed[0].reason
    assert scan._isolated(con, str(p))
    for vol in ("V", "?"):
        s = scan.scan_tree(con, str(kat), volume=vol, now=NOW)
        assert s.isolated == 1, vol
    assert con.execute("SELECT count(*) FROM location").fetchone()[0] == 1
    assert _loc(con, p)["header_hash"] == loc["header_hash"]
    w = writeback.recover_torn(con, op_id, now=NOW)
    assert w.status == "blocked" and f"finish_inplace({op_id})" in w.reason

    f = writeback.finish_inplace(con, op_id, now=NOW)
    assert f.status == "applied", f
    assert _operacje(con)[0]["phase"] == "synced" and not scan._isolated(con, str(p))
    assert [r["status"] for r in writeback.pending_for_run(con, "R")] == ["applied"]
    assert _loc(con, p)["header_hash"] == _hash(p) != loc["header_hash"]
    assert writeback.finish_inplace(con, op_id, now=NOW).status == "blocked"
    con.close()


def test_zwolnienie_reka_dziala_dla_operacji_written(tmp_path, monkeypatch):
    p = _fits(tmp_path / "zw.fits")
    con, _ = _baza_z_plikiem(tmp_path, p)
    _zerwany_udzial(monkeypatch)
    writeback.commit(con, "R", now=NOW, inplace=True)
    monkeypatch.undo()
    op_id = _operacje(con)[0]["id"]
    repo.release_inplace_op(con, op_id=op_id, now=NOW, reason="sprawdzone ręcznie")
    assert _operacje(con)[0]["phase"] == "released" and not scan._isolated(con, str(p))
    con.close()


def test_odzysk_z_nieudanym_resynciem_zostaje_otwarty_i_da_sie_ponowic(tmp_path, monkeypatch):
    """Odzysk przywrócił region, ale re-sync padł: dawniej faza `recovered` padała PRZED re-synciem
    i zdejmowała izolację. Teraz operacja zostaje `unverified`, a ponowiony odzysk (region stary
    to też stan pośredni) kończy się `recovered`."""
    p = _fits(tmp_path / "r.fits")
    con, op, przed = _otwarta_operacja(tmp_path, monkeypatch, p)
    prawdziwy = scan.scan_file
    _zerwany_udzial(monkeypatch)
    w1 = writeback.recover_torn(con, op["id"], now=NOW)
    monkeypatch.setattr(writeback.scan, "scan_file", prawdziwy)
    assert w1.status == "failed" and f"recover_torn({op['id']})" in w1.reason
    assert p.read_bytes() == przed and _operacje(con)[0]["phase"] == "unverified"
    assert scan._isolated(con, str(p))
    w2 = writeback.recover_torn(con, op["id"], now=NOW)
    assert w2.status == "restored", w2
    assert _operacje(con)[0]["phase"] == "recovered" and not scan._isolated(con, str(p))
    con.close()


def _skan_z_przeplotem(tmp_path, monkeypatch, *, odczyt_pada):
    """Skan drzewa, w którym zapis w miejscu (pełny commit) wchodzi PO bramce izolacji, a PRZED
    ingestem rekordu - rekord skanu niesie stan sprzed zapisu (albo odczyt pada)."""
    kat = tmp_path / "arch"
    kat.mkdir()
    p = _fits(kat / "a.fits")
    con, loc = _baza_z_plikiem(tmp_path, p)
    os.utime(p, (1_700_000_000, 1_700_000_000))          # brama przyrostowa musi przeczytać plik
    prawdziwy = scan.scan_file
    stan = {"raz": True}

    def _przeplot(path, **kw):
        if not (stan["raz"] and path == str(p)):
            return prawdziwy(path, **kw)                 # m.in. re-sync pisarza w środku
        stan["raz"] = False
        rec = prawdziwy(path)                            # odczyt skanu: stan SPRZED zapisu
        assert len(writeback.commit(con, "R", now=NOW, inplace=True).in_place) == 1
        if odczyt_pada:
            raise OSError(64, "The specified network name is no longer available")
        return rec
    monkeypatch.setattr(scan, "scan_file", _przeplot)
    s = scan.scan_tree(con, str(kat), volume="V", now=NOW)
    monkeypatch.undo()
    return con, p, loc, s


def test_skan_przeplatany_z_zapisem_nie_przywraca_starych_faktow(tmp_path, monkeypatch):
    """Skan przeczytał plik przed zapisem w miejscu, a zapis zakończył się przed ingestem: dawniej
    spóźniony ingest przywracał stary nagłówek w bazie. Teraz generacja z bramki odrzuca rekord
    (operacja ma większe `id`), a jedno ponowienie z nową generacją (AR-17 (7)) trafia na bramę
    przyrostową - plik opisał już re-sync pisarza, więc pominięcie; baza opisuje plik po zapisie."""
    con, p, loc, s = _skan_z_przeplotem(tmp_path, monkeypatch, odczyt_pada=False)
    assert (s.isolated, s.isolated_paths, s.skipped) == (0, [], 1), s
    assert _loc(con, p)["header_hash"] == _hash(p) != loc["header_hash"]
    assert con.execute("SELECT header_hash FROM location").fetchone()[0] == _hash(p)
    con.close()


def test_skan_blad_odczytu_w_trakcie_zapisu_bez_markera(tmp_path, monkeypatch):
    """Odczyt skanu padł w trakcie zapisu w miejscu: bez markera nieczytelności (plik niczym nie
    zawinił); ponowienie z nową generacją pomija plik opisany już przez re-sync pisarza."""
    con, p, _, s = _skan_z_przeplotem(tmp_path, monkeypatch, odczyt_pada=True)
    assert (s.isolated, s.skipped, s.frame_review) == (0, 1, 0), s
    assert con.execute("SELECT unreadable_since FROM location").fetchone()[0] is None
    con.close()


def test_generacja_odrzuca_w_transakcji_klingi(tmp_path):
    """Strażnik generacji w klindze faktów kopii (wąskie okno między sprawdzeniem w `ingest_record`
    a zapisem): operacja nowsza niż generacja → `StaleScanRecord`, zero zapisu."""
    p = _fits(tmp_path / "g.fits")
    con, loc = _baza_z_plikiem(tmp_path, p)
    gen = repo.inplace_generation(con)
    writeback.commit(con, "R", now=NOW, inplace=True)
    przed = _loc(con, p)["header_hash"]
    with pytest.raises(repo.StaleScanRecord):
        repo.refresh_location_unreadable(
            con, location_id=loc["id"], sha1_data="x", path=str(p), mtime="m", reason="r",
            kind="io", now=NOW, inplace_gen=gen)
    with pytest.raises(repo.StaleScanRecord):
        scan.ingest_record(con, scan.scan_file(str(p)), volume="V", now=NOW,
                           summary=scan.ScanSummary(), inplace_gen=gen)
    assert _loc(con, p)["header_hash"] == przed
    assert con.execute("SELECT unreadable_since FROM location").fetchone()[0] is None
    con.close()


def test_spozniony_odzysk_nie_cofa_nowszego_commitu(tmp_path, monkeypatch):
    """Drugie wywołanie odzysku widziało operację OTWARTĄ przed blokadą; zanim ją dostało, pierwsze
    odzyskało plik, a user ponownie zapisał TĘ SAMĄ wartość (region = „stan pośredni" starej
    operacji). Dawniej spóźniony odzysk cofał ten poprawny commit. Teraz faza i brak nowszej
    operacji są sprawdzane POD blokadą → 'blocked', plik zostaje po nowym commicie."""
    p = _fits(tmp_path / "s.fits")
    con, op, _ = _otwarta_operacja(tmp_path, monkeypatch, p)
    prawdziwy = writeback._exclusive
    stan = {"raz": True}

    import contextlib

    @contextlib.contextmanager
    def _przeplot(path):
        if stan["raz"]:
            stan["raz"] = False
            assert writeback.recover_torn(con, op["id"], now=NOW).status == "restored"
            _stage(con, "R2", _loc(con, p)["id"], "NGC 6992", _hash(p))
            assert len(writeback.commit(con, "R2", now=NOW, inplace=True).in_place) == 1
            stan["po_nowym"] = p.read_bytes()
        with prawdziwy(path) as fh:
            yield fh
    monkeypatch.setattr(writeback, "_exclusive", _przeplot)

    w = writeback.recover_torn(con, op["id"], now=NOW)
    assert w.status == "blocked", w
    assert fits.getheader(str(p))["OBJECT"] == "NGC 6992" and p.read_bytes() == stan["po_nowym"]
    assert [o["phase"] for o in _operacje(con)] == ["recovered", "synced"]
    con.close()


def test_nieutrwalona_faza_written_to_operacja_nieukonczona(tmp_path, monkeypatch):
    """Zapis zweryfikowany, ale przejście do `written` nie zapisało się w bazie: dawniej 'applied'
    z dopiskiem. Teraz 'failed' (operacja nieukończona), faza `writing` - izolowana; odzysk wraca
    do pliku sprzed zapisu."""
    p = _fits(tmp_path / "w.fits")
    przed = p.read_bytes()
    con, _ = _baza_z_plikiem(tmp_path, p)
    prawdziwa = repo.set_inplace_op_phase

    def _pada(con_, **kw):
        if kw["phase"] == "written":
            raise sqlite3.OperationalError("database is locked")
        return prawdziwa(con_, **kw)
    monkeypatch.setattr(writeback.repo, "set_inplace_op_phase", _pada)
    res = writeback.commit(con, "R", now=NOW, inplace=True)
    monkeypatch.undo()
    assert not res.applied and len(res.failed) == 1 and "NIEUKOŃCZONA" in res.failed[0].reason
    (op_id, _, faza), = [tuple(o) for o in _operacje(con)]
    assert faza == "writing" and scan._isolated(con, str(p))
    assert f"recover_torn({op_id})" in res.failed[0].reason
    assert writeback.recover_torn(con, op_id, now=NOW).status == "restored"
    assert p.read_bytes() == przed
    con.close()


def test_nieutrwalona_faza_synced_zostawia_izolacje(tmp_path, monkeypatch):
    """Re-sync udany, ale transakcja zamknięcia (`synced` + wpisy stagingu) nie zapisała się:
    dawniej 'applied' przy lokacji bez zamkniętej operacji. Teraz 'failed', faza `written`
    (izolowana), wpis stagingu NIE 'applied', a `finish_inplace` kończy - kontrola danych liczona
    od nowa wobec kotwicy operacji przechodzi, choć baza opisuje już plik po zapisie."""
    p = _fits(tmp_path / "y.fits")
    con, _ = _baza_z_plikiem(tmp_path, p)

    def _pada(con_, **kw):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(writeback.repo, "finish_inplace_op", _pada)
    res = writeback.commit(con, "R", now=NOW, inplace=True)
    monkeypatch.undo()
    assert not res.applied and "'synced' NIE zapisana" in res.failed[0].reason
    op_id = _operacje(con)[0]["id"]
    assert _operacje(con)[0]["phase"] == "written" and scan._isolated(con, str(p))
    assert _loc(con, p)["header_hash"] == _hash(p)                  # re-sync przeszedł
    assert writeback.finish_inplace(con, op_id, now=NOW).status == "applied"
    assert _operacje(con)[0]["phase"] == "synced"
    assert [r["status"] for r in writeback.pending_for_run(con, "R")] == ["applied"]
    con.close()


def test_ponowione_undo_po_obcej_zmianie_regionu_blokuje(tmp_path, monkeypatch):
    """Undo w miejscu przywróciło nagłówek, re-sync padł (`written`); potem OBCA zmiana tego samego
    regionu. Dawniej ponowione undo robiło sam re-sync i wciągało obcy nagłówek jako „cofnięte".
    Teraz pod blokadą region != wynik cofnięcia → 'blocked', baza nietknięta, izolacja trwa."""
    p = _fits(tmp_path / "x.fits")
    con, _ = _baza_z_plikiem(tmp_path, p)
    res = writeback.commit(con, "R", now=NOW, inplace=True)
    po_commicie = _loc(con, p)["header_hash"]
    prawdziwy = scan.scan_file
    _zerwany_udzial(monkeypatch)
    assert len(writeback.undo(con, res.commit_id, now=NOW).failed) == 1
    monkeypatch.setattr(writeback.scan, "scan_file", prawdziwy)
    dane = bytearray(p.read_bytes())
    slot = dane.index(b"OBJECT  = ")
    dane[slot:slot + 80] = fits.Card("OBJECT", "NGC 7000", KOMENTARZ).image.encode("ascii")
    p.write_bytes(bytes(dane))
    u2 = writeback.undo(con, res.commit_id, now=NOW)
    assert not u2.restored and len(u2.blocked) == 1, u2
    assert "nie jest wynikiem" in u2.blocked[0].reason
    assert _operacje(con)[-1]["phase"] == "written" and _loc(con, p)["header_hash"] == po_commicie
    assert fits.getheader(str(p))["OBJECT"] == "NGC 7000"
    con.close()


def test_bramka_izolacji_przed_kazda_mutacja_pliku(tmp_path, monkeypatch):
    """Lokacja z nieukończonym zapisem w miejscu (`written`) - każda inna mutacja pliku odmawia
    z drogą naprawy: commit atomowy i w miejscu, undo innego commitu, rename; także otwarcie nowej
    operacji w klindze. Plik bajt w bajt nietknięty."""
    p = _fits(tmp_path / "b.fits")
    con, loc = _baza_z_plikiem(tmp_path, p)
    _stage(con, "A", loc["id"], "NGC 6992", loc["header_hash"])
    atomowy = writeback.commit(con, "A", now=NOW)                  # wcześniejszy commit atomowy
    assert len(atomowy.applied) == 1 and not atomowy.in_place
    h = _hash(p)
    _stage(con, "W", loc["id"], "NGC 7000", h)
    _zerwany_udzial(monkeypatch)
    assert len(writeback.commit(con, "W", now=NOW, inplace=True).failed) == 1
    monkeypatch.undo()
    op_id = _operacje(con)[0]["id"]
    zamrozony = p.read_bytes()

    for run, inplace in (("B", False), ("B2", True)):
        _stage(con, run, loc["id"], "M 42", _hash(p))
        wynik = writeback.commit(con, run, now=NOW, inplace=inplace)
        assert len(wynik.blocked) == 1 and f"finish_inplace({op_id})" in wynik.blocked[0].reason
    u = writeback.undo(con, atomowy.commit_id, now=NOW)
    assert len(u.blocked) == 1 and f"finish_inplace({op_id})" in u.blocked[0].reason
    repo.stage_rename(con, run_id="N", location_id=loc["id"], old_path=str(p),
                      new_path=str(tmp_path / "nowa.fits"),
                      expected_mtime=con.execute("SELECT mtime FROM location WHERE id = ?",
                                                 (loc["id"],)).fetchone()[0])
    rn = writeback.commit_renames(con, "N", now=NOW)
    assert len(rn.blocked) == 1 and "izolowany" in rn.blocked[0].reason
    with pytest.raises(ValueError):
        repo.begin_inplace_undo(con, commit_id=None, location_id=loc["id"],
                                spec=writeback._spec_z_operacji(
                                    con.execute("SELECT * FROM inplace_op").fetchone()), now=NOW)
    assert p.read_bytes() == zamrozony and p.exists()
    con.close()


# ============================================================ KOTWICA, STAGING, POWRÓT, STRAŻ (2026-09-27)
# Generacja w każdej drodze czytającej plik kopii, kotwica utrwalona przy operacji, wiązanie wpisów
# stagingu z operacją, droga powrotu z `written`, tryb ścisły kotwicy i straż podmiany atomowej.
# Każdy test zarzutu pada na kodzie sprzed tej tury.


def _bez_faktow(con, path, *, bez_odcisku=False):
    """Kopia jak sprzed 0021 (fakty kopii NULL), a z `bez_odcisku` - jak XISF sprzed P6a (także
    `header_hash` NULL). Tylko test: tak wyglądają wiersze, które sterowniki uzupełnień wybierają."""
    con.execute("UPDATE location SET hdr_filter = NULL, hdr_imagetyp = NULL, hdr_object = NULL, "
                "hdr_telescop = NULL, hdr_instrume = NULL, hdr_exptime = NULL, "
                "hdr_xbinning = NULL, hdr_date_obs = NULL, image_count = NULL, "
                "image_roles = NULL, hdr_hash = NULL, hdr_rule = NULL WHERE path = ?", (str(path),))
    if bez_odcisku:
        con.execute("UPDATE location SET header_hash = NULL WHERE path = ?", (str(path),))
    con.commit()


def _odczyt_przed_zapisem(monkeypatch, nazwa, p, zapis):
    """Podmienia `scan.<nazwa>` tak, że PIERWSZY odczyt pliku `p` przez sterownik czyta go, potem
    w środku odczytu wykonuje `zapis()` (commit w miejscu), a oddaje stan SPRZED zapisu - odczyt
    przeszedł bramkę izolacji, zanim operacja powstała. Kolejne wołania (re-sync pisarza) - wprost."""
    prawdziwy = getattr(scan, nazwa)
    stan = {"raz": True}

    def _przeplot(path, *a, **kw):
        if not (stan["raz"] and str(path) == str(p)):
            return prawdziwy(path, *a, **kw)
        stan["raz"] = False
        wynik = prawdziwy(path, *a, **kw)
        zapis()
        return wynik
    monkeypatch.setattr(scan, nazwa, _przeplot)


def _commit_z_padem_resyncu(monkeypatch, con, run):
    """Commit w miejscu, którego re-sync pada (czkawka odczytu) - operacja zostaje `written`,
    baza opisuje plik SPRZED zapisu."""
    with monkeypatch.context() as m:
        _zerwany_udzial(m)
        wynik = writeback.commit(con, run, now=NOW, inplace=True)
    assert len(wynik.failed) == 1 and _operacje(con)[-1]["phase"] == "written", wynik
    return wynik


def test_uzupelnienie_xisf_przeplatane_z_zapisem_nie_przywraca_starych_faktow(tmp_path,
                                                                            monkeypatch):
    """Uzupełnienie XISF przeczytało plik przed zapisem w miejscu, a zapis skończył się (`synced`)
    przed wciągnięciem rekordu. Dawniej `ingest_record` bez generacji przywracał w bazie stary
    nagłówek. Teraz generacja sprzed bramki odrzuca rekord, a jedno ponowienie (AR-17 (7): nowa
    generacja, bramka, odczyt) wciąga plik PO zapisie - `failed` puste, baza opisuje plik po zapisie."""
    p = _xisf(tmp_path / "a.xisf")
    con, loc = _baza_z_plikiem(tmp_path, p)
    _bez_faktow(con, p, bez_odcisku=True)

    def _zapis():
        assert len(writeback.commit(con, "R", now=NOW, inplace=True).in_place) == 1
    _odczyt_przed_zapisem(monkeypatch, "scan_file", p, _zapis)
    s = scan.backfill_xisf_headers(con, now=NOW)
    monkeypatch.undo()
    assert (s.read, s.failed, s.remaining) == (1, 0, 0), s
    assert _loc(con, p)["header_hash"] == _hash(p) != loc["header_hash"]
    con.close()


def test_uzupelnienie_xisf_nie_wciaga_pliku_uszkodzonego_a_dokonczenie_mu_nie_ufa(tmp_path,
                                                                                monkeypatch):
    """Scenariusz recenzji: uzupełnienie XISF przeszło bramkę, zapis w miejscu zmienił przy zapisie
    bajt drugiego obrazu (kontrola danych → `written`), a uzupełnienie przeczytało plik JUŻ
    uszkodzony. Dawniej wciągało jego fakty (`location.file_sha1` = sha1 pliku uszkodzonego),
    a `finish_inplace` brało „sha1 == kotwica" za dowód synchronizacji → 'applied'/`synced`.
    Teraz rekord odpada na generacji, a dokończenie liczy kontrolę wobec kotwicy operacji."""
    p, zly = _xisf_dwa_obrazy(tmp_path / "d.xisf")
    con, loc = _baza_z_plikiem(tmp_path, p)
    _bez_faktow(con, p, bez_odcisku=True)
    prawdziwy = scan.scan_file
    stan = {"raz": True}

    def _przeplot(path, **kw):
        if not (stan["raz"] and str(path) == str(p)):
            return prawdziwy(path, **kw)
        stan["raz"] = False
        with monkeypatch.context() as m:
            _psuj_bajt_przy_fsync(m, zly)
            wynik = writeback.commit(con, "R", now=NOW, inplace=True)
        assert len(wynik.failed) == 1 and "POZA regionem" in wynik.failed[0].reason
        return prawdziwy(path)                         # odczyt PO zapisie - plik uszkodzony
    monkeypatch.setattr(scan, "scan_file", _przeplot)
    s = scan.backfill_xisf_headers(con, now=NOW)
    monkeypatch.undo()
    assert s.failed == 1, s
    assert _loc(con, p)["header_hash"] is None                     # fakty uszkodzonego NIE weszły
    op_id = _operacje(con)[0]["id"]
    f = writeback.finish_inplace(con, op_id, now=NOW)
    assert f.status == "failed" and f"recover_torn({op_id})" in f.reason, f
    assert _operacje(con)[0]["phase"] == "written" and scan._isolated(con, str(p))
    assert [r["status"] for r in writeback.pending_for_run(con, "R")] == ["failed"]
    con.close()


def test_dokonczenie_nie_ufa_kotwicy_przestawionej_w_bazie(tmp_path, monkeypatch):
    """Kotwica kontroli danych żyje przy operacji, nie w `location.file_sha1`: obcy zapis faktów
    (tu `ingest_record` bez generacji - np. import) przestawia kolumnę na sha1 pliku z bajtem
    zmienionym poza nagłówkiem. Dawniej `finish_inplace` brał równość z nią za dowód → 'applied'
    i `synced`. Teraz kontrola liczona od nowa wobec kotwicy operacji → 'failed' z drogą powrotu."""
    p, zly = _fits_dwa_hdu(tmp_path / "k.fits")
    przed = p.read_bytes()
    con, loc = _baza_z_plikiem(tmp_path, p)
    _psuj_bajt_przy_fsync(monkeypatch, zly)
    res = writeback.commit(con, "R", now=NOW, inplace=True)
    monkeypatch.undo()
    assert len(res.failed) == 1 and "POZA regionem" in res.failed[0].reason
    op_id = _operacje(con)[0]["id"]
    import hashlib
    scan.ingest_record(con, scan.scan_file(str(p)), volume="V", now=NOW,
                       summary=scan.ScanSummary())                 # kolumna mutowalna przestawiona
    assert con.execute("SELECT file_sha1 FROM location").fetchone()[0] == hashlib.sha1(
        p.read_bytes()).hexdigest()
    f = writeback.finish_inplace(con, op_id, now=NOW)
    assert f.status == "failed" and "POZA regionem" in f.reason, f
    assert _operacje(con)[0]["phase"] == "written"
    assert con.execute("SELECT anchor_sha1 FROM inplace_op").fetchone()[0] == hashlib.sha1(
        przed).hexdigest()                                         # kotwica przy operacji
    con.close()


def test_uzupelnienie_faktow_kopii_przeplatane_z_zapisem_nie_pisze(tmp_path, monkeypatch):
    """Uzupełnienie faktów kopii przeczytało nagłówek przed zapisem w miejscu, a zapis zostawił
    operację `written` (re-sync padł - baza wciąż ma stary odcisk). Kotwica odcisku sama tego nie
    łapie: dawniej fakty STAREGO nagłówka lądowały na lokacji izolowanej. Teraz generacja odrzuca
    zapis w klindze, a ponowienie (AR-17 (7)) trafia na bramkę izolacji (`written`) → `failed`
    „kopia izolowana", fakty zostają puste."""
    p = _xisf(tmp_path / "c.xisf")
    con, _ = _baza_z_plikiem(tmp_path, p)
    _bez_faktow(con, p)
    _odczyt_przed_zapisem(monkeypatch, "_read_meta", p,
                          lambda: _commit_z_padem_resyncu(monkeypatch, con, "R"))
    s = scan.backfill_copy_facts(con, now=NOW)
    monkeypatch.undo()
    assert (s.read, s.written, s.stale, s.failed) == (1, 0, 0, 1), s
    assert "izolowana" in s.failed_paths[0]
    assert _loc(con, p)["header_hash"] is not None
    assert con.execute("SELECT hdr_hash FROM location").fetchone()[0] is None
    con.close()


def test_przejecie_zeznania_przeplatane_z_zapisem_nie_przejmuje(tmp_path, monkeypatch):
    """Przejęcie zeznania ocalałej kopii przeczytało plik przed zapisem w miejscu, a zapis zostawił
    operację `written` (baza wciąż ma stary odcisk, więc kotwica klingi przepuszcza). Dawniej
    `header` klatki dostawał zeznanie nagłówka, którego na dysku już nie ma. Teraz generacja
    odrzuca przejęcie, a ponowienie (AR-17 (7)) trafia na bramkę izolacji (`written`) → `failed`
    „kopia izolowana", zero `header.adopted`."""
    root = tmp_path / "ARCH"
    (root / "A").mkdir(parents=True)
    (root / "B").mkdir()
    a = _fits(root / "A" / "a.fits", obj="NGC6992")
    b = _fits(root / "B" / "b.fits", obj="NGC 7000")
    con = db.open_db(str(tmp_path / "h.db"))
    scan.scan_tree(con, str(root), volume="V", now=NOW)
    la, lb = _loc(con, a), _loc(con, b)
    assert la["frame_id"] == lb["frame_id"]
    os.remove(a)
    assert repo.mark_location_vanished(con, location_id=la["id"], expected_path=str(a),
                                       root=str(root / "A"), run_id="t", now=NOW)
    assert [f for f, _k in scan.adopt_candidates(con)] == [lb["frame_id"]]
    _stage(con, "R", lb["id"], "M 42", lb["header_hash"])
    _odczyt_przed_zapisem(monkeypatch, "scan_file", b,
                          lambda: _commit_z_padem_resyncu(monkeypatch, con, "R"))
    s = scan.adopt_orphan_testimony(con, now=NOW)
    monkeypatch.undo()
    assert (s.adopted, s.raced, s.failed) == (0, 0, 1), s
    assert "izolowana" in s.failed_paths[0]
    assert con.execute("SELECT count(*) FROM event WHERE verb = 'header.adopted'").fetchone()[0] == 0
    assert con.execute("SELECT object_raw FROM header").fetchone()[0] == "NGC6992"
    con.close()


class _Przerwa(BaseException):
    """Symulacja przerwania procesu (zabity proces, utrata zasilania) - nie `Exception`, więc żadna
    obrona `except Exception` pisarza jej nie połknie."""


def test_przerwa_po_written_dokonczenie_domyka_staging_i_nagrobek(tmp_path, monkeypatch):
    """Proces przerwał się po utrwaleniu `written`, przed re-synciem i przed oznaczeniem stagingu:
    wpis zostaje 'pending', nagrobek ręki stoi. Ponowny commit odbija się od izolacji ('blocked').
    Dawniej `finish_inplace` dobierał tylko wpisy 'failed': synchronizował bazę i stawiał `synced`,
    a wpis zostawał, nagrobek nie gasł, kolejny commit dostawał `header_hash mismatch`. Teraz
    operacja zna SWOJE wpisy (0023) i dokończenie zamyka je atomowo z fazą i nagrobkiem - bez
    dotykania wpisu innej lokacji tego przebiegu."""
    p = _fits(tmp_path / "n.fits")
    q = _fits(tmp_path / "q.fits", seed=5)
    con, loc = _baza_z_plikiem(tmp_path, p)
    _scan_in(con, q)
    _stage(con, "R", _loc(con, q)["id"], "M 42", "zly-odcisk")      # druga lokacja przebiegu
    con.execute("UPDATE frame SET object_source = 'user_cleared' WHERE id = ?", (loc["frame_id"],))
    con.commit()

    def _przerwij(*a, **kw):
        raise _Przerwa()
    monkeypatch.setattr(writeback, "_dokoncz", _przerwij)
    with pytest.raises(_Przerwa):
        writeback.commit(con, "R", now=NOW, inplace=True)
    monkeypatch.undo()
    (op_id, _, faza), = [tuple(o) for o in _operacje(con)]
    assert faza == "written"
    statusy = lambda: {r["location_id"]: r["status"] for r in writeback.pending_for_run(con, "R")}
    assert statusy()[loc["id"]] == "pending"

    ponowny = writeback.commit(con, "R", now=NOW, inplace=True)
    assert [f.path for f in ponowny.blocked] == [str(p), str(q)]
    assert f"finish_inplace({op_id})" in ponowny.blocked[0].reason

    f = writeback.finish_inplace(con, op_id, now=NOW)
    assert f.status == "applied", f
    assert statusy() == {loc["id"]: "applied", _loc(con, q)["id"]: "blocked"}
    assert con.execute("SELECT object_source FROM frame WHERE id = ?",
                       (loc["frame_id"],)).fetchone()[0] is None
    assert con.execute("SELECT count(*) FROM event WHERE verb = 'object.tombstone_cleared'"
                       ).fetchone()[0] == 1
    assert _operacje(con)[0]["phase"] == "synced" and _loc(con, p)["header_hash"] == _hash(p)
    assert fits.getheader(str(p))["OBJECT"] == "NGC 6992"
    trzeci = writeback.commit(con, "R", now=NOW, inplace=True)
    assert not (trzeci.applied or trzeci.blocked or trzeci.failed)
    con.close()


def test_ponowny_commit_po_odzysku_przerwy_wiaze_wpisy_na_nowo(tmp_path, monkeypatch):
    """Legalne ponowienie nie może utknąć na wiązaniu: przerwa PO utrwaleniu operacji (faza
    `writing`, wpis 'pending' związany z nią), odzysk przywraca plik (`recovered`), a ponowny commit
    tego samego przebiegu wiąże wpis z NOWĄ operacją i przechodzi."""
    p = _fits(tmp_path / "po.fits")
    przed = p.read_bytes()
    con, loc = _baza_z_plikiem(tmp_path, p)

    def _przerwij(*a, **kw):
        raise _Przerwa()
    monkeypatch.setattr(writeback, "_verify_inplace", _przerwij)
    with pytest.raises(_Przerwa):
        writeback.commit(con, "R", now=NOW, inplace=True)
    monkeypatch.undo()
    (op_id, _, faza), = [tuple(o) for o in _operacje(con)]
    (wpis,) = writeback.pending_for_run(con, "R")
    assert faza == "writing" and wpis["status"] == "pending"
    assert writeback.recover_torn(con, op_id, now=NOW).status == "restored"
    assert p.read_bytes() == przed
    res = writeback.commit(con, "R", now=NOW, inplace=True)
    assert len(res.in_place) == 1, res
    assert con.execute("SELECT inplace_op_id FROM pending_changes").fetchone()[0] == \
        _operacje(con)[-1]["id"] != op_id
    assert [r["status"] for r in writeback.pending_for_run(con, "R")] == ["applied"]
    con.close()


def _dryf_poza_naglowkiem(p, offset):
    """Plik zmieniony poza nagłówkiem od ostatniego skanu, z ZACHOWANYM `mtime` (narzędzie, które
    przywraca znacznik czasu, albo zegar serwera) - reguła `mtime` pisarza tego nie widzi."""
    st = os.stat(p)
    dane = bytearray(p.read_bytes())
    dane[offset] ^= 0xFF
    p.write_bytes(bytes(dane))
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns))
    assert os.stat(p).st_mtime_ns == st.st_mtime_ns
    return bytes(dane)


def test_dryf_przy_tym_samym_mtime_ma_droge_powrotu(tmp_path, monkeypatch):
    """Plik zmienił się poza nagłówkiem przy zachowanym `mtime`: tryb domyślny pisze, kontrola
    danych po zapisie wykrywa różnicę → `written`. Dawniej lokacja stała bez drogi wyjścia
    (dokończenie powtarza błąd, undo wymaga dokończenia, odzysk odmawia `written`, skan pomija).
    Teraz `recover_torn` przywraca stary nagłówek w miejscu (plik = stan sprzed zapisu z dryfem),
    faza `recovered`, wpis stagingu 'failed' z prawdziwym powodem, `mtime` lokacji NULL - skan
    przeczyta plik w całości, a potem nowy commit przechodzi."""
    kat = tmp_path / "arch"
    kat.mkdir()
    p, zly = _fits_dwa_hdu(kat / "d.fits")
    con, loc = _baza_z_plikiem(tmp_path, p)
    z_dryfem = _dryf_poza_naglowkiem(p, zly)
    ino = os.stat(p).st_ino
    res = writeback.commit(con, "R", now=NOW, inplace=True)
    assert len(res.failed) == 1 and "POZA regionem" in res.failed[0].reason, res
    op_id = _operacje(con)[0]["id"]
    assert f"recover_torn({op_id})" in res.failed[0].reason
    assert writeback.finish_inplace(con, op_id, now=NOW).status == "failed"
    assert len(writeback.undo(con, res.commit_id, now=NOW).restored) == 0

    w = writeback.recover_torn(con, op_id, now=NOW)
    assert w.status == "restored" and "poza nagłówkiem" in w.reason and "przeskanuj" in w.reason, w
    assert p.read_bytes() == z_dryfem and os.stat(p).st_ino == ino
    assert _operacje(con)[0]["phase"] == "recovered" and not scan._isolated(con, str(p))
    assert con.execute("SELECT mtime FROM location").fetchone()[0] is None
    (wpis,) = writeback.pending_for_run(con, "R")
    assert wpis["status"] == "failed" and "przeskanuj" in wpis["reason"]
    ev = con.execute("SELECT reason FROM event WHERE verb = 'location.writeback_reverted'"
                     ).fetchone()
    assert ev is not None and "poza nagłówkiem" in ev["reason"]
    assert writeback.recover_torn(con, op_id, now=NOW).status == "blocked"   # zamknięta

    s = scan.scan_tree(con, str(kat), volume="V", now=NOW)
    assert s.isolated == 0 and s.locations_refreshed == 1
    import hashlib
    assert con.execute("SELECT file_sha1 FROM location").fetchone()[0] == hashlib.sha1(
        z_dryfem).hexdigest()
    _stage(con, "R2", loc["id"], "NGC 6992", _hash(p))
    assert len(writeback.commit(con, "R2", now=NOW, inplace=True).in_place) == 1
    con.close()


def test_powrot_nie_cofa_poprawnego_zapisu(tmp_path, monkeypatch):
    """Droga powrotu z `written` dotyczy WYŁĄCZNIE nieudanej kontroli danych: operacja `written`
    po czkawce re-syncu (kontrola przechodzi) → 'blocked' z drogą `finish_inplace`, plik nietknięty,
    faza bez zmian. Powrót nie jest drugim undo."""
    p = _fits(tmp_path / "ok.fits")
    con, _ = _baza_z_plikiem(tmp_path, p)
    _commit_z_padem_resyncu(monkeypatch, con, "R")
    po_zapisie = p.read_bytes()
    op_id = _operacje(con)[0]["id"]
    w = writeback.recover_torn(con, op_id, now=NOW)
    assert w.status == "blocked" and f"finish_inplace({op_id})" in w.reason, w
    assert p.read_bytes() == po_zapisie and _operacje(con)[0]["phase"] == "written"
    assert writeback.finish_inplace(con, op_id, now=NOW).status == "applied"
    con.close()


def test_przerwany_powrot_da_sie_ponowic(tmp_path, monkeypatch):
    """Powrót przywrócił stary region, ale transakcja zamknięcia padła: operacja zostaje `written`
    ze starym regionem (stan pośredni), dokończenie odsyła do powrotu, a ponowiony powrót nie pisze
    i od razu zamyka operację."""
    p, zly = _fits_dwa_hdu(tmp_path / "pp.fits")
    con, _ = _baza_z_plikiem(tmp_path, p)
    z_dryfem = _dryf_poza_naglowkiem(p, zly)
    writeback.commit(con, "R", now=NOW, inplace=True)
    op_id = _operacje(con)[0]["id"]

    def _pada(con_, **kw):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(writeback.repo, "revert_inplace_op", _pada)
    w1 = writeback.recover_torn(con, op_id, now=NOW)
    monkeypatch.undo()
    assert w1.status == "failed" and f"recover_torn({op_id})" in w1.reason, w1
    assert p.read_bytes() == z_dryfem and _operacje(con)[0]["phase"] == "written"
    d = writeback.finish_inplace(con, op_id, now=NOW)
    assert d.status == "blocked" and f"recover_torn({op_id})" in d.reason, d
    assert writeback.recover_torn(con, op_id, now=NOW).status == "restored"
    assert _operacje(con)[0]["phase"] == "recovered" and p.read_bytes() == z_dryfem
    con.close()


def test_tryb_scisly_blokuje_dryf_przed_operacja(tmp_path, monkeypatch):
    """Tryb pilotażu (`fallback=False`) = tryb ścisły kotwicy: pełny odczyt pod blokadą przed
    `begin_inplace_*` niezależnie od `mtime` → dryf poza nagłówkiem przy tym samym `mtime` to
    'blocked', bez operacji w dzienniku, plik nietknięty. Dawniej pilotaż pisał i zostawiał
    `written`. Plik czysty w trybie ścisłym przechodzi, a kotwica z pełnego odczytu trafia do
    operacji. Tryb domyślny (wsad) przy zgodnym `mtime` NIE czyta całego pliku przed zapisem."""
    p, zly = _fits_dwa_hdu(tmp_path / "s.fits")
    con, loc = _baza_z_plikiem(tmp_path, p)
    z_dryfem = _dryf_poza_naglowkiem(p, zly)
    res = writeback.commit(con, "R", now=NOW, inplace=True, fallback=False)
    assert len(res.blocked) == 1 and "od ostatniego skanu" in res.blocked[0].reason, res
    assert not _operacje(con) and p.read_bytes() == z_dryfem

    import hashlib
    q = _fits(tmp_path / "czysty.fits", seed=9)
    przed = q.read_bytes()
    _scan_in(con, q)
    lq = _loc(con, q)
    _stage(con, "S", lq["id"], "NGC 6992", lq["header_hash"])
    assert len(writeback.commit(con, "S", now=NOW, inplace=True, fallback=False).in_place) == 1
    assert _operacje(con)[-1]["phase"] == "synced"
    assert con.execute("SELECT anchor_sha1 FROM inplace_op").fetchone()[0] == hashlib.sha1(
        przed).hexdigest()

    r = _fits(tmp_path / "wsad.fits", seed=11)
    _scan_in(con, r)
    lr = _loc(con, r)
    _stage(con, "W", lr["id"], "NGC 6992", lr["header_hash"])
    pelne = []
    prawdziwy = writeback._sha1_uchwytu
    monkeypatch.setattr(writeback, "_sha1_uchwytu", lambda fh: pelne.append(1) or prawdziwy(fh))
    assert len(writeback.commit(con, "W", now=NOW, inplace=True).in_place) == 1
    assert pelne == []
    con.close()


@pytest.mark.parametrize("faza_b", ["written", "synced"])
def test_commit_atomowy_przeplatany_z_zapisem_w_miejscu(tmp_path, monkeypatch, faza_b):
    """Commit atomowy A przeszedł bramkę izolacji i przygotował plik tymczasowy; zanim zrobił
    `os.replace`, commit B zapisał plik w miejscu (i został `written` albo `synced`). Dawniej A
    podmieniał plik, ścierając zapis B, i meldował 'applied'. Teraz podmiana idzie pod strażą
    w transakcji zapisu bazy: operacja B (izolująca albo nowsza niż generacja A) → A 'blocked',
    plik = wynik B, plik tymczasowy sprzątnięty."""
    p = _fits(tmp_path / "a.fits")
    con, loc = _baza_z_plikiem(tmp_path, p)                 # przebieg "R" = zapis w miejscu (B)
    _stage(con, "A", loc["id"], "M 42", loc["header_hash"])  # przebieg "A" = droga atomowa
    prawdziwy = repo.insert_header_backup
    stan = {"raz": True}

    def _przeplot(con_, **kw):
        if stan["raz"]:
            stan["raz"] = False
            if faza_b == "written":
                _commit_z_padem_resyncu(monkeypatch, con, "R")
            else:
                assert len(writeback.commit(con, "R", now=NOW, inplace=True).in_place) == 1
            stan["po_b"] = p.read_bytes()
        return prawdziwy(con_, **kw)
    monkeypatch.setattr(writeback.repo, "insert_header_backup", _przeplot)
    a = writeback.commit(con, "A", now=NOW)
    monkeypatch.undo()
    assert not a.applied and len(a.blocked) == 1, a
    assert f"operacja {_operacje(con)[0]['id']}" in a.blocked[0].reason
    assert p.read_bytes() == stan["po_b"] and fits.getheader(str(p))["OBJECT"] == "NGC 6992"
    assert [x.name for x in tmp_path.iterdir() if x.suffix == ".tmp"] == []
    assert _operacje(con)[0]["phase"] == faza_b
    # Backup A powstał przed podmianą (wiersz commitu w bazie zostaje, append-only), ale żaden plik
    # nie został podmieniony - wynik nie oddaje `commit_id`, więc żadna powierzchnia nie pokaże
    # „Cofnij" commitu, który niczego nie zmienił.
    assert a.commit_id is None, a
    wb_worker = pytest.importorskip("horreum.gui.wb_worker")
    assert wb_worker.commit_do_cofniecia(a) is None
    con.close()


@pytest.mark.parametrize("powod, recznie", [
    ("operacja 1 jest w fazie synced, nie czeka na dokończenie", True),
    (f"inny plik niż w chwili zapisu (rozmiar/st_ino); {writeback._RECZNA}", False),
], ids=["faza", "recepta_reczna"])
def test_dokonczenie_zablokowane_wskazuje_gest_zwolnienia(tmp_path, monkeypatch, powod, recznie):
    """Dokończenie zapisu w miejscu odmówiło ('blocked') - powód commitu wskazuje drogę zwolnienia,
    którą człowiek ma: gest „Zwolnij plik do skanu…" (etykieta z katalogu) albo
    `writeback.release_isolation` (zwolnienie pod blokadą pliku z CAS fazy), nie klingę bazy
    `repo.release_inplace_op`. Powód, który już niesie receptę ręczną (`_RECZNA`), nie dostaje jej
    drugi raz.

    Falsyfikator: przywróć w `commit` dopisek `repo.release_inplace_op(N)` → asercje padają."""
    from horreum.gui.i18n_catalog import CATALOG
    p = _fits(tmp_path / "z.fits")
    con, _loc_ = _baza_z_plikiem(tmp_path, p)
    monkeypatch.setattr(writeback, "_dokoncz",
                        lambda con_, op_id, *, now: writeback.WriteResult("blocked", powod, None))
    res = writeback.commit(con, "R", now=NOW, inplace=True)
    monkeypatch.undo()
    (f,) = res.failed
    assert "release_inplace_op" not in f.reason, f.reason
    gest = f"„{CATALOG['grid.inplace.release']['pl']}”"
    assert f.reason.count(gest) == 1 and f.reason.count("writeback.release_isolation") == 1, f.reason
    if recznie:
        assert f"writeback.release_isolation({_operacje(con)[0]['id']})" in f.reason, f.reason
    con.close()


# ============================================================ SKRYPT KONTROLI PILOTAŻU (Z16)


def _skrypt():
    sciezka = Path(__file__).resolve().parents[1] / "scripts" / "kontrola_pilotazu.py"
    spec = importlib.util.spec_from_file_location("kontrola_pilotazu", sciezka)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_skrypt_blokada_nie_rusza_cudzego_pliku_i_mierzy_inny_proces(tmp_path):
    k = _skrypt()
    cudzy = tmp_path / "horreum_proba_blokady.bin"
    cudzy.write_bytes(b"cudze")
    wyniki = k.blokada(str(tmp_path))
    assert wyniki["kod"] == 0, wyniki
    assert wyniki["zapis z INNEGO procesu"] == "odrzucone" and wyniki["os.replace na plik"] == "odrzucone"
    assert cudzy.read_bytes() == b"cudze"
    assert sorted(x.name for x in tmp_path.iterdir()) == ["horreum_proba_blokady.bin"]
    with pytest.raises(SystemExit):
        k.blokada(r"R:\ASTRO_\LIGHTS")


def test_skrypt_po_porownuje_z_planem(tmp_path):
    """Z16: `po` przepuszcza WYŁĄCZNIE zmianę OBJECT na oczekiwaną formę z tym samym komentarzem."""
    k = _skrypt()
    p = _fits(tmp_path / "pl.fits")
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps([{"plik": str(p), "object": "NGC 6992"}]), encoding="utf-8")
    kopie = tmp_path / "kopie"
    k.przed(str(kopie), str(plan))
    assert writeback.write_changes_inplace(str(p), _op(), _hash(p)).status == "applied"
    assert k.po(str(kopie)) == 0
    with fits.open(str(p), mode="update") as hdul:             # obca zmiana innej karty
        hdul[0].header["IMAGETYP"] = "Dark"
    assert k.po(str(kopie)) == 1


# ============================================================ PLAN UJEDNOLICENIA (predykat + silnik)


def _baza_planu(tmp_path):
    con = db.open_db(str(tmp_path / "h.db"))
    pliki = {
        "veil": _fits(tmp_path / "veil.fits", obj="NGC6992", seed=1),
        "m106": _fits(tmp_path / "m106.fits", obj="M 106", seed=2),
        "gotowa": _fits(tmp_path / "gotowa.fits", obj="NGC 7000", seed=3),
        "ksiezyc": _fits(tmp_path / "ksiezyc.fits", obj="ksiezyc", seed=4),
        "obca": _fits(tmp_path / "obca.fits", obj="Mglawica Zdzinia", seed=5),
        "xisf": _xisf(tmp_path / "stos.xisf", obj="'NGC6992'", payload=b"\x09" * 32),
        "dwie": _fits(tmp_path / "dwie.fits", obj="NGC6960", seed=6),
    }
    for p in pliki.values():
        _scan_in(con, p)
    kopia = tmp_path / "kopia" / "dwie.fits"                  # druga OBECNA kopia tej samej klatki
    kopia.parent.mkdir()
    kopia.write_bytes(pliki["dwie"].read_bytes())
    _scan_in(con, kopia)
    resolver.run_resolver(con, NOW)
    return con, pliki


def test_plan_predykat_bramki_i_podglad(tmp_path):
    con, pliki = _baza_planu(tmp_path)
    rows = {r["path"]: r for r in queries.object_card_form_rows(con)}

    assert str(pliki["gotowa"]) not in rows                    # już w formie
    assert str(pliki["obca"]) not in rows                      # nierozpoznana - inne zeznanie
    assert rows[str(pliki["m106"])]["form"] == "NGC 4258"
    assert rows[str(pliki["ksiezyc"])]["form"] == "Moon"
    assert rows[str(pliki["dwie"])]["skip"].startswith("wiele obecnych kopii")
    assert queries.object_card_form_frame_ids(con) == {
        r["frame_id"] for r in rows.values() if r["skip"] is None}

    plan = macro.plan_object_card_form(rows.values(), run_id="U")
    assert {(t.path, t.old_value, t.new_value) for t in plan.run.touched} == {
        (str(pliki["veil"]), "NGC6992", "NGC 6992"), (str(pliki["m106"]), "M 106", "NGC 4258"),
        (str(pliki["ksiezyc"]), "ksiezyc", "Moon"), (str(pliki["xisf"]), "NGC6992", "NGC 6992")}
    assert plan.swaps[0] == ("NGC6992", "NGC 6992", 2)
    assert (plan.in_place, plan.fallback) == (4, 0)
    assert [s.reason for s in plan.run.skipped] == ["wiele obecnych kopii (2)"]
    con.close()


def test_plan_wykonanie_w_miejscu_i_idempotencja(tmp_path):
    """Staging JEDNĄ transakcją + istniejący commit w trybie w miejscu; obiekty klatek bez zmian;
    drugi plan (także po kolejnym przebiegu resolvera) jest pusty."""
    con, pliki = _baza_planu(tmp_path)
    obiekty = dict(con.execute("SELECT id, object_id FROM frame").fetchall())
    plan = macro.plan_object_card_form(queries.object_card_form_rows(con), run_id="U")
    assert repo.stage_pending_many(con, run_id="U", previews=plan.run.touched) == 4

    postep = []
    res = writeback.commit(con, "U", now=NOW, inplace=True,
                           progress=lambda d, t, p, s: postep.append((d, t, s)))
    assert len(res.applied) == 4 and len(res.in_place) == 4 and not res.failed, res
    assert postep[-1] == (4, 4, "applied")
    assert fits.getheader(str(pliki["m106"]))["OBJECT"] == "NGC 4258"
    assert fits.getheader(str(pliki["m106"])).comments["OBJECT"] == KOMENTARZ

    resolver.run_resolver(con, NOW)
    assert dict(con.execute("SELECT id, object_id FROM frame").fetchall()) == obiekty
    drugi = macro.plan_object_card_form(queries.object_card_form_rows(con))
    assert not drugi.run.touched and not drugi.swaps
    con.close()


def test_plan_anulowanie_zostawia_reszte_pending(tmp_path):
    con, _ = _baza_planu(tmp_path)
    plan = macro.plan_object_card_form(queries.object_card_form_rows(con), run_id="U")
    repo.stage_pending_many(con, run_id="U", previews=plan.run.touched)
    licznik = iter(range(100))
    res = writeback.commit(con, "U", now=NOW, inplace=True,
                           should_cancel=lambda: next(licznik) >= 2)
    assert res.cancelled and len(res.applied) == 2
    statusy = [r["status"] for r in writeback.pending_for_run(con, "U")]
    assert statusy.count("applied") == 2 and statusy.count("pending") == 2
    con.close()


def test_przewidywanie_drogi_zgodne_z_pisarzem(tmp_path):
    """`inplace_route` (podgląd bez pliku) i pisarz na pliku używają tej samej reguły rekordu."""
    assert writeback.inplace_route("fits", "OBJECT", "NGC 6992", "str", KOMENTARZ) is None
    powod = writeback.inplace_route("fits", "OBJECT", "V" * 20, "str", "k" * 47)
    p = _fits(tmp_path / "r.fits", obj="M31", comment="k" * 47)
    res = writeback.write_changes_inplace(str(p), _op("V" * 20), _hash(p), journal=_NieWolno())
    assert isinstance(res, writeback.Fallback) and res.reason == powod
    assert writeback.inplace_route("xisf", "OBJECT", "V" * 60, "str", None) is None


def test_plan_komentarz_bez_miejsca_pomija_z_powodem_pisarza(tmp_path):
    """AR-47: karta, której zastany komentarz nie przeżyje nowej formy, odmawia w OBU drogach
    (w miejscu - spadek, atomowo - AR-7), więc plan ją POMIJA z powodem, który dałby zapis
    atomowy, zamiast liczyć „spadek na drogę dotychczasową". Ta sama forma z krótkim komentarzem
    wchodzi w miejscu.

    Falsyfikator: zdejmij `comment_loss_route` z planu → klatka w `touched` i `fallback == 1`,
    a commit da 'blocked'."""
    p = _fits(tmp_path / "dlugi.fits", obj="M31", comment="k" * 47)
    wiersz = {"skip": None, "frame_id": 1, "path": str(p), "location_id": 1, "card": "M31",
              "form": "V" * 20, "header_hash": _hash(p), "filetype": "fits",
              "value_type": "str", "comment": "k" * 47}
    plan = macro.plan_object_card_form([wiersz], run_id="U")
    assert not plan.run.touched and (plan.in_place, plan.fallback) == (0, 0)
    (pominiety,) = plan.run.skipped
    zapis = writeback.write_changes(str(p), _op("V" * 20), _hash(p))
    assert zapis.status == "blocked" and pominiety.reason == zapis.reason

    krotki = macro.plan_object_card_form([dict(wiersz, comment=KOMENTARZ[:10])], run_id="U")
    assert len(krotki.run.touched) == 1 and krotki.in_place == 1
    assert writeback.comment_loss_route("xisf", "OBJECT", "V" * 60, "k" * 70) is None


def test_plan_bramki_formy_sklejki_typu_i_sumy(tmp_path):
    """kimi Z1/Z2c/Z5 + astra Z5 w predykacie: kanon znany tylko z aliasu (forma nie wraca), sklejka
    z członem wskazującym co innego, karta nietekstowa, FITS z CHECKSUM - każde pominięte z powodem;
    sklejka, której OBA człony wskazują ten sam obiekt, wchodzi."""
    from horreum.resolve._text import norm_alnum
    con = db.open_db(str(tmp_path / "h.db"))
    alias = _fits(tmp_path / "alias.fits", obj="Zupelnie Wymyslona 77", seed=11)
    skl_zla = _fits(tmp_path / "skl_zla.fits", obj="NGC6992_Mglawica Zdzinia", seed=12)
    skl_ok = _fits(tmp_path / "skl_ok.fits", obj="NGC4258_M 106", seed=13)
    typ = _fits(tmp_path / "typ.fits", obj="NGC6888", seed=14)
    suma = tmp_path / "suma.fits"
    hdu = fits.PrimaryHDU(data=np.full((4, 4), 15, dtype=np.int16))
    hdu.header["IMAGETYP"] = "Light"
    hdu.header["OBJECT"] = "NGC2403"
    hdu.writeto(suma, checksum=True)
    for p in (alias, skl_zla, skl_ok, typ, suma):
        _scan_in(con, p)
    resolver.run_resolver(con, NOW)
    fid = _loc(con, alias)["frame_id"]
    repo.user_assign_object(con, alias_norm=norm_alnum("Zupelnie Wymyslona 77"), canon="ZW77",
                            catalog=None, kind="own", frame_ids=[fid], now=NOW)
    con.execute("UPDATE cards SET value_type = 'int' WHERE frame_id = ? AND keyword = 'OBJECT'",
                (_loc(con, typ)["frame_id"],))                         # poza klingą: tylko test
    con.commit()
    rows = {r["path"]: r for r in queries.object_card_form_rows(con)}

    assert rows[str(alias)]["skip"].startswith("forma karty nie wraca do kanonu")
    assert rows[str(skl_zla)]["skip"].startswith("sklejka oznaczeń")
    assert rows[str(skl_ok)]["skip"] is None and rows[str(skl_ok)]["form"] == "NGC 4258"
    assert rows[str(typ)]["skip"] == "karta OBJECT nietekstowa (int)"
    assert rows[str(suma)]["skip"] == "FITS z sumą kontrolną (CHECKSUM/DATASUM)"
    con.close()


def test_forma_karty_ta_sama_co_gesty_gui():
    """kimi Z1: GUI i wsad biorą formę z jednej Qt-wolnej funkcji."""
    pytest.importorskip("PySide6")
    from horreum.gui import app as app_mod
    assert app_mod.forma_karty_object is resolver.forma_karty_object
