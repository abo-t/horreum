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
                        lambda path: dataclasses.replace(prawdziwy(path), sha1_data="f" * 40))
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

    def _czkawka(path):
        if path == str(pierwszy):
            raise OSError(64, "The specified network name is no longer available")
        return prawdziwy(path)
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
    domyślnie spadek na drogę atomową z powodem w wyniku."""
    p = _fits(tmp_path / "e.fits", obj="M31", comment="k" * 47)
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
    assert fits.getheader(str(p))["OBJECT"] == "V" * 20
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
                        lambda path: (_ for _ in ()).throw(OSError(64, "zerwany udział")))
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
    """Z13, przypadek 2 (astra): commit bez udanego re-syncu (baza ma hash A sprzed commitu), undo
    przywraca A, jego re-sync też pada. Rozpoznanie po `header_hash` uznałoby to za „już cofnięte";
    faza operacji mówi prawdę - ponowienie robi re-sync."""
    p = _fits(tmp_path / "v.fits")
    con, loc = _baza_z_plikiem(tmp_path, p)
    prawdziwy = scan.scan_file
    monkeypatch.setattr(writeback.scan, "scan_file",
                        lambda path: (_ for _ in ()).throw(OSError(64, "zerwany udział")))
    res = writeback.commit(con, "R", now=NOW, inplace=True)
    assert len(res.failed) == 1
    u1 = writeback.undo(con, res.commit_id, now=NOW)
    assert len(u1.failed) == 1
    assert _loc(con, p)["header_hash"] == loc["header_hash"]        # baza wciąż ma hash A
    monkeypatch.setattr(writeback.scan, "scan_file", prawdziwy)
    u2 = writeback.undo(con, res.commit_id, now=NOW)
    assert len(u2.restored) == 1 and "dokończono synchronizację" in u2.restored[0].reason
    assert [o["phase"] for o in _operacje(con)] == ["written", "synced"]
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
