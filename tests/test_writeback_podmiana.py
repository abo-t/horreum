"""Droga atomowa pisarza: podmiana systemowa z kopią pliku wypartego (AR-18), bajtowe cofnięcie
(AR-19), backup niepotwierdzony i rekoncyliacja z dyskiem (AR-40) oraz kompensacja renamu pod jedną
blokadą bazy (AR-56).

Każdy mechanizm z wstrzykniętą awarią w punkcie między krokami, na prawdziwych plikach FITS i XISF
(fikstury `test_writeback`). „Inny pisarz" to zapis z tego samego procesu przez zwykły uchwyt -
blokada `_exclusive` odróżnia uchwyty, nie procesy, więc test jest wierny zachowaniu systemu."""

from __future__ import annotations

import ctypes
import hashlib
import os
import shutil
import sqlite3

import numpy as np
import pytest
from astropy.io import fits

from horreum import db, repo, scan, writeback
from test_undo_nagrobek import _baza_z_nagrobkiem, _stan as _stan_nagrobka
from test_writeback import NOW, _loc_id, _plik, _scan_in, _stage


class _Smierc(BaseException):
    """Śmierć procesu w punkcie wstrzyknięcia - przechodzi przez każde `except Exception` pisarza."""


def _baza(tmp_path, fmt, name="a", run="R", value="EQ6"):
    con = db.open_db(str(tmp_path / "h.db"))
    p = _plik(tmp_path, fmt, name=name)
    _scan_in(con, p)
    lid = _loc_id(con, p)
    _stage_teleskop(con, run, lid, value)
    return con, p, lid


def _stage_teleskop(con, run, lid, value="EQ6"):
    hh = con.execute("SELECT header_hash FROM location WHERE id=?", (lid,)).fetchone()[0]
    _stage(con, run, lid, "TELESCOP", "set", value, "str", expected=hh)


def _resztki(tmp_path):
    """Pliki tymczasowe i kopie plików wypartych zostawione w katalogu."""
    return sorted(x.name for x in tmp_path.iterdir()
                  if x.suffix == ".tmp" or x.name.endswith(writeback._KOPIA_SUFFIX))


def _backupy(con):
    return [dict(r) for r in con.execute(
        "SELECT id, commit_id, pending_since, unreplaced_at, header_text FROM header_backups "
        "ORDER BY id")]


def _hh(con, lid):
    return con.execute("SELECT header_hash FROM location WHERE id=?", (lid,)).fetchone()[0]


def _sha(p):
    return hashlib.sha1(p.read_bytes()).hexdigest()


# ============================================================ AR-18: podmiana systemowa


@pytest.mark.parametrize("fmt", ["fits", "xisf"])
def test_commit_potwierdza_backup_i_sprzata_kopie(tmp_path, fmt):
    """Zwykły commit drogą atomową: kopia pliku wypartego znika, backup potwierdzony w transakcji
    podmiany (`pending_since` NULL) i niesie sha1 całego pliku sprzed zapisu (kotwica AR-19)."""
    con, p, lid = _baza(tmp_path, fmt)
    przed = _sha(p)
    res = writeback.commit(con, "R", now=NOW)
    assert len(res.applied) == 1 and res.applied[0].reason is None, res
    assert _resztki(tmp_path) == []
    (b,) = _backupy(con)
    assert b["pending_since"] is None and b["unreplaced_at"] is None
    assert writeback.RegionBackup.decode(b["header_text"]).file_sha1 == przed
    con.close()


@pytest.mark.parametrize("fmt", ["fits", "xisf"])
def test_przygotowanie_pod_blokada_odcina_innych_pisarzy(tmp_path, monkeypatch, fmt):
    """Odczyt, plik tymczasowy i odcisk powstają pod `_exclusive`: w tej chwili zapis innym
    uchwytem i podmiana pliku są odrzucane przez system, więc ogon i region pochodzą z jednej
    wersji. Falsyfikator: zdejmij `with _exclusive(path)` z pisarza - oba otwarcia przechodzą."""
    con, p, lid = _baza(tmp_path, fmt)
    obcy = tmp_path / "obcy.bin"
    obcy.write_bytes(b"obcy")
    proby = {}
    prawdziwy = writeback._odcisk

    def _podglad(fh, offset, length):
        if proby:                     # tylko pierwszy odcisk - pod blokadą, z uchwytu pliku usera
            return prawdziwy(fh, offset, length)
        for nazwa, akcja in (("zapis", lambda: open(p, "r+b").close()),
                             ("podmiana", lambda: os.replace(obcy, p))):
            try:
                akcja()
                proby[nazwa] = "przeszło"
            except PermissionError:
                proby[nazwa] = "odrzucone"
        return prawdziwy(fh, offset, length)
    monkeypatch.setattr(writeback, "_odcisk", _podglad)
    res = writeback.commit(con, "R", now=NOW)
    assert proby == {"zapis": "odrzucone", "podmiana": "odrzucone"}
    assert len(res.applied) == 1, res
    con.close()


@pytest.mark.parametrize("fmt", ["fits", "xisf"])
@pytest.mark.parametrize("rodzaj", ["w_miejscu", "podmiana_pliku"])
def test_cudza_zmiana_w_oknie_podmiany_wraca_na_miejsce(tmp_path, monkeypatch, fmt, rodzaj):
    """Sedno AR-18: między zwolnieniem blokady a podmianą inny pisarz zmienia plik (w miejscu albo
    własną podmianą). Rewalidacja kopii pliku wypartego to widzi: wersja tamtego pisarza wraca pod
    ścieżkę bajt w bajt, nasza przepada, wynik 'blocked', backup oznaczony jako bez podmiany, baza
    bez re-syncu, zero resztek. Falsyfikator: zdejmij `_oddaj_wyparty` z `_podmien` - plik niesie
    naszą wersję zbudowaną ze stanu sprzed zmiany innego pisarza (jego zmiana ginie)."""
    con, p, lid = _baza(tmp_path, fmt)
    hh_przed = _hh(con, lid)
    cudzy = {}
    _cudza_podmiana_w_oknie(monkeypatch, cudzy, rodzaj)
    res = writeback.commit(con, "R", now=NOW)
    monkeypatch.undo()
    assert not res.applied and len(res.blocked) == 1, [f.reason for f in res.failed] or res
    assert "zmienił się między odczytem a podmianą" in res.blocked[0].reason
    assert p.read_bytes() == cudzy["bajty"]                    # cudza zmiana żyje
    assert _resztki(tmp_path) == []
    (b,) = _backupy(con)
    assert b["unreplaced_at"] == NOW and b["pending_since"] is None
    assert res.commit_id is None and _hh(con, lid) == hh_przed
    con.close()


def _zmien_cudzo(path, rodzaj, bajt):
    """Inny pisarz zmienia ostatni bajt pliku: w miejscu (z `mtime` +1 s) albo własną podmianą
    (plik tymczasowy + `os.replace`). Zwraca bajty jego wersji."""
    if rodzaj == "w_miejscu":
        with open(path, "r+b") as fh:
            fh.seek(-1, os.SEEK_END)
            fh.write(bajt)
        st = os.stat(path)
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 10 ** 9))
    else:
        zast = path + ".zast"
        shutil.copyfile(path, zast)
        with open(zast, "r+b") as fh:
            fh.seek(-1, os.SEEK_END)
            fh.write(bajt)
        os.replace(zast, path)
    return open(path, "rb").read()


def _cudza_podmiana_w_oknie(monkeypatch, cudzy, rodzaj="podmiana_pliku"):
    """Inny pisarz zmienia plik tuż przed NASZĄ podmianą (pierwsze wywołanie prymitywu); kolejne
    wywołania (powrót wypartego) idą do prawdziwego prymitywu."""
    prawdziwy = writeback._replace_file_w

    def _okno(path, tmp, kopia):
        if "bajty" not in cudzy:
            cudzy["bajty"] = _zmien_cudzo(path, rodzaj, b"\x55")
        prawdziwy(path, tmp, kopia)
    monkeypatch.setattr(writeback, "_replace_file_w", _okno)


def _powrot_zajety(monkeypatch, ile):
    """Powrót kopii pod ścieżkę (zamiennikiem jest kopia pliku wypartego) zajęty przez `ile`
    pierwszych prób - jak na udziale SMB `R:` (sonda zarządcy 2026-10-05: 'failed' z „ręcznie”
    w wariancie FITS)."""
    prawdziwy = writeback._replace_file_w
    stan = {"n": 0}

    def _replace(path, zamiennik, kopia):
        if str(zamiennik).endswith(writeback._KOPIA_SUFFIX) and stan["n"] < ile:
            stan["n"] += 1
            raise ctypes.WinError(32)
        prawdziwy(path, zamiennik, kopia)
    monkeypatch.setattr(writeback, "_replace_file_w", _replace)
    monkeypatch.setattr(writeback.time, "sleep", lambda s: None)
    return stan


@pytest.mark.parametrize("fmt", ["fits", "xisf"])
def test_powrot_wypartego_ponawia_blad_przejsciowy(tmp_path, monkeypatch, fmt):
    """Powrót wersji innego pisarza trafia na chwilowo zajęty plik (32): ponowienie, potem zwykłe
    'blocked' i plik innego pisarza na miejscu. Falsyfikator: `_oddaj_wyparty` bez
    `_kopia_na_miejsce` - 'failed' z „przenieś … ręcznie”, jak w sondzie na `R:`."""
    con, p, lid = _baza(tmp_path, fmt)
    cudzy = {}
    _cudza_podmiana_w_oknie(monkeypatch, cudzy)
    stan = _powrot_zajety(monkeypatch, 2)
    res = writeback.commit(con, "R", now=NOW)
    monkeypatch.undo()
    assert len(res.blocked) == 1 and stan["n"] == 2, [f.reason for f in res.failed] or res
    assert p.read_bytes() == cudzy["bajty"] and _resztki(tmp_path) == []
    con.close()


@pytest.mark.parametrize("fmt", ["fits", "xisf"])
def test_powrot_wypartego_niemozliwy_obie_wersje_zostaja_i_powod_mowi_gdzie(tmp_path, monkeypatch,
                                                                            fmt):
    """Powrót nie wychodzi nawet po ponowieniach: 'failed', pod ścieżką NASZA wersja, wersja innego
    pisarza bajt w bajt pod kopią, której nikt nie kasuje, a powód podaje obie ścieżki - nic nie
    ginie, nic nie znika po cichu."""
    con, p, lid = _baza(tmp_path, fmt)
    cudzy = {}
    _cudza_podmiana_w_oknie(monkeypatch, cudzy)
    _powrot_zajety(monkeypatch, 99)
    res = writeback.commit(con, "R", now=NOW)
    monkeypatch.undo()
    (f,) = res.failed
    (kopia,) = [x for x in tmp_path.iterdir() if x.name.endswith(writeback._KOPIA_SUFFIX)]
    assert kopia.read_bytes() == cudzy["bajty"]
    assert p.read_bytes() != cudzy["bajty"] and b"EQ6" in p.read_bytes()   # nasza wersja
    assert str(kopia) in f.reason and str(p) in f.reason and "ręcznie" in f.reason
    assert [x for x in tmp_path.iterdir() if x.suffix == ".tmp"] == []
    con.close()


@pytest.mark.parametrize("fmt", ["fits", "xisf"])
def test_trzeci_pisarz_w_oknie_powrotu_wszystkie_wersje_zostaja(tmp_path, monkeypatch, fmt):
    """A1: w oknie powrotu wersji B (innego pisarza z okna podmiany) trzeci pisarz podmienia plik
    na C. Powrót zachowuje plik wypierany spod ścieżki i sprawdza, że to NASZA wersja - tu nie jest:
    'failed', pod ścieżką B, pod drugą kopią C, obie ścieżki w powodzie, nic nie zginęło.
    Falsyfikator: powrót bez sprawdzenia wypieranego - C znika, wynik 'blocked' mówi, że cudza
    wersja wróciła."""
    con, p, lid = _baza(tmp_path, fmt)
    cudzy = {}
    _cudza_podmiana_w_oknie(monkeypatch, cudzy)
    przed_powrotem = writeback._replace_file_w

    def _trzeci(path, zamiennik, kopia):
        if str(zamiennik).endswith(writeback._KOPIA_SUFFIX) and "c" not in cudzy:
            cudzy["c"] = _zmien_cudzo(path, "podmiana_pliku", b"\x66")
        przed_powrotem(path, zamiennik, kopia)
    monkeypatch.setattr(writeback, "_replace_file_w", _trzeci)
    res = writeback.commit(con, "R", now=NOW)
    monkeypatch.undo()
    (f,) = res.failed
    assert p.read_bytes() == cudzy["bajty"]                               # B na miejscu
    (zwrotna,) = [x for x in tmp_path.iterdir() if x.name.endswith(writeback._KOPIA_SUFFIX)]
    assert zwrotna.read_bytes() == cudzy["c"]                             # C zachowane
    assert str(p) in f.reason and str(zwrotna) in f.reason and "ręcznie" in f.reason
    assert [x for x in tmp_path.iterdir() if x.suffix == ".tmp"] == []
    con.close()


@pytest.mark.parametrize("fmt", ["fits", "xisf"])
def test_blad_1177_kopia_wraca_pod_sciezke(tmp_path, monkeypatch, fmt):
    """ERROR_UNABLE_TO_MOVE_REPLACEMENT_2: plik wyparty JEST już pod nazwą kopii, a zamiennik nie
    dotarł - pod ścieżką nic. Pisarz przenosi kopię z powrotem: plik bajt w bajt jak przed,
    'failed', backup NIEPOTWIERDZONY (AR-40). Ponowny zapis tej zmiany (nowy staging) najpierw
    rozstrzyga go z dyskiem (`unreplaced_at`: na dysku nagłówek sprzed commitu), potem pisze."""
    con, p, lid = _baza(tmp_path, fmt)
    przed = p.read_bytes()

    def _1177(path, tmp, kopia):
        os.rename(path, kopia)
        raise ctypes.WinError(1177)
    monkeypatch.setattr(writeback, "_replace_file_w", _1177)
    res = writeback.commit(con, "R", now=NOW)
    monkeypatch.undo()
    assert len(res.failed) == 1 and "niepotwierdzona" in res.failed[0].reason, res
    assert p.read_bytes() == przed and _resztki(tmp_path) == []
    (b,) = _backupy(con)
    assert b["pending_since"] == NOW and b["unreplaced_at"] is None

    _stage_teleskop(con, "R2", lid)
    res2 = writeback.commit(con, "R2", now=NOW)
    assert len(res2.applied) == 1, res2
    b1, b2 = _backupy(con)
    assert (b1["pending_since"], b1["unreplaced_at"]) == (None, NOW)       # cofnięcie go pominie
    assert (b2["pending_since"], b2["unreplaced_at"]) == (None, None)
    ures = writeback.undo(con, b1["commit_id"], now=NOW)
    assert not ures.restored and not ures.blocked and not ures.failed, ures
    assert p.read_bytes() != przed                                         # zmiana R2 stoi
    con.close()


def test_blad_przejsciowy_podmiany_ponawia(tmp_path, monkeypatch):
    """32 (naruszenie współdzielenia - antywirus, indeksowanie) przy stanie nietkniętym: krótkie
    ponowienie, potem zwykły sukces. Falsyfikator: bez pętli `_replace_z_ponowieniem` - 'failed'."""
    con, p, lid = _baza(tmp_path, "fits")
    prawdziwy = writeback._replace_file_w
    licznik = {"n": 0}

    def _raz_zajety(path, tmp, kopia):
        licznik["n"] += 1
        if licznik["n"] == 1:
            raise ctypes.WinError(32)
        prawdziwy(path, tmp, kopia)
    monkeypatch.setattr(writeback, "_replace_file_w", _raz_zajety)
    monkeypatch.setattr(writeback.time, "sleep", lambda s: None)
    res = writeback.commit(con, "R", now=NOW)
    assert len(res.applied) == 1 and licznik["n"] == 2, res
    assert _backupy(con)[0]["pending_since"] is None and _resztki(tmp_path) == []
    con.close()


def test_kopia_nieusuwalna_zostaje_i_wynik_to_mowi(tmp_path, monkeypatch):
    """Kopia pliku wypartego, której nie da się skasować: zapis 'applied', a powód podaje jej
    ścieżkę; kopia jest bajt w bajt plikiem sprzed zapisu (nic nie ginie, nic nie znika po cichu)."""
    con, p, lid = _baza(tmp_path, "fits")
    przed = p.read_bytes()
    prawdziwy = os.remove

    def _remove(sciezka):
        if str(sciezka).endswith(writeback._KOPIA_SUFFIX):
            raise PermissionError(13, "plik otwarty")
        prawdziwy(sciezka)
    monkeypatch.setattr(writeback.os, "remove", _remove)
    monkeypatch.setattr(writeback.time, "sleep", lambda s: None)
    res = writeback.commit(con, "R", now=NOW)
    monkeypatch.undo()
    (a,) = res.applied
    (kopia,) = [x for x in tmp_path.iterdir() if x.name.endswith(writeback._KOPIA_SUFFIX)]
    assert str(kopia) in a.reason and kopia.read_bytes() == przed
    con.close()


# ============================================================ AR-19: cofnięcie bajtowe


def _fits_bzero_przestawione(path):
    """FITS `uint16` (BZERO/BSCALE) z kartami w kolejności BZERO przed BSCALE - astropy przy zapisie
    commitu układa je odwrotnie, więc cofnięcie przez ponowną serializację nie odda bajtów."""
    hdu = fits.PrimaryHDU(data=np.arange(16, dtype=np.uint16).reshape(4, 4))
    hdu.header["TELESCOP"] = "RC8"
    hdu.header["IMAGETYP"] = "Light"
    hdu.writeto(path, overwrite=True)
    raw = bytearray(path.read_bytes())
    rek = [bytes(raw[i:i + 80]) for i in range(0, 2880, 80)]
    iz = next(i for i, r in enumerate(rek) if r.startswith(b"BZERO"))
    isc = next(i for i, r in enumerate(rek) if r.startswith(b"BSCALE"))
    rek[iz], rek[isc] = rek[isc], rek[iz]
    raw[0:2880] = b"".join(rek)
    path.write_bytes(bytes(raw))
    return path


def _commit_bzero(tmp_path):
    con = db.open_db(str(tmp_path / "h.db"))
    p = _fits_bzero_przestawione(tmp_path / "u16.fits")
    _scan_in(con, p)
    lid = _loc_id(con, p)
    _stage_teleskop(con, "R", lid)
    przed = p.read_bytes()
    res = writeback.commit(con, "R", now=NOW)
    assert len(res.applied) == 1 and p.read_bytes() != przed, res
    return con, p, lid, res.commit_id, przed


def test_cofniecie_atomowe_fits_wraca_bajt_w_bajt(tmp_path):
    """Sedno AR-19 (przykład z rejestru - kolejność BZERO/BSCALE): cofnięcie commitu drogi atomowej
    oddaje CAŁY plik bajt w bajt, wynik bez powodu i bez `semantic`."""
    con, p, lid, cid, przed = _commit_bzero(tmp_path)
    ures = writeback.undo(con, cid, now=NOW)
    assert len(ures.restored) == 1 and not ures.semantic, ures
    assert ures.restored[0].reason is None
    assert p.read_bytes() == przed
    con.close()


def test_cofniecie_semantyczne_mowi_semantycznie(tmp_path, monkeypatch):
    """Gdy region backupu nie pasuje do układu pliku, zostaje droga semantyczna - i wynik mówi to
    wprost: powód „cofnięte semantycznie", plik w `UndoResult.semantic`. Ten sam plik drogą
    semantyczną NIE wraca bajt w bajt (dowód, że rozróżnienie jest potrzebne).
    Falsyfikator: `_sync(..., None)` po `write_full_header` - cofnięcie semantyczne udaje bajtowe."""
    con, p, lid, cid, przed = _commit_bzero(tmp_path)
    monkeypatch.setattr(writeback, "_plan_przywrocenia", lambda *a, **kw: None)
    ures = writeback.undo(con, cid, now=NOW)
    (r,) = ures.restored
    assert ures.semantic == [r] and r.reason.startswith(writeback._COFNIETE_SEMANTYCZNIE), ures
    assert fits.getheader(str(p))["TELESCOP"] == "RC8" and p.read_bytes() != przed
    con.close()


@pytest.mark.parametrize("fmt", ["fits", "xisf"])
def test_cofniecie_koperty_bez_sha1_mowi_ze_calego_pliku_nie_porownano(tmp_path, fmt):
    """Koperta sprzed AR-19 (bez `file_sha1`): region wraca bajt w bajt, ale całego pliku nie ma
    z czym porównać - wynik to mówi i nie liczy się jako semantyczny."""
    con, p, lid = _baza(tmp_path, fmt)
    przed = p.read_bytes()
    res = writeback.commit(con, "R", now=NOW)
    (b,) = _backupy(con)
    env = writeback.RegionBackup.decode(b["header_text"])
    stara = writeback.RegionBackup(env.fmt, env.offset, env.region, env.size, env.ino,
                                   env.pre_hash).encode()
    con.execute("UPDATE header_backups SET header_text = ? WHERE id = ?", (stara, b["id"]))
    con.commit()
    ures = writeback.undo(con, res.commit_id, now=NOW)
    (r,) = ures.restored
    assert not ures.semantic and "całego pliku nie porównano" in r.reason, ures
    assert p.read_bytes() == przed
    con.close()


# ============================================================ AR-40: backup niepotwierdzony


def _smierc_przed_podmiana(monkeypatch):
    def _f(*a, **kw):
        raise _Smierc()
    monkeypatch.setattr(writeback, "_podmien", _f)


def _smierc_po_podmianie(monkeypatch):
    """Podmiana zaszła, proces zginął przed potwierdzeniem backupu i przed re-synciem."""
    prawdziwy = writeback._podmien

    def _f(tmp, path, replace_guard, odcisk, po_podmianie=None):
        prawdziwy(tmp, path, replace_guard, odcisk, None)
        raise _Smierc()
    monkeypatch.setattr(writeback, "_podmien", _f)


@pytest.mark.parametrize("fmt", ["fits", "xisf"])
def test_smierc_przed_podmiana_stary_commit_nie_cofa_nowego(tmp_path, monkeypatch, fmt):
    """Scenariusz AR-40: proces ginie po utrwaleniu backupu, przed podmianą. Backup zostaje
    NIEPOTWIERDZONY, plik nietknięty, wpisy 'pending'. Ponowiony commit tej samej zmiany najpierw
    rozstrzyga go z dyskiem (nagłówek sprzed commitu → `unreplaced_at`), potem pisze. Cofnięcie
    STAREGO commitu nie ma czego cofać i nie rusza zapisu nowego - dawniej oba backupy miały ten
    sam `post_hash`, a cofnięcie starego cofało nagłówek należący do nowego."""
    con, p, lid = _baza(tmp_path, fmt)
    przed = p.read_bytes()
    _smierc_przed_podmiana(monkeypatch)
    with pytest.raises(_Smierc):
        writeback.commit(con, "R", now=NOW)
    monkeypatch.undo()
    (b,) = _backupy(con)
    assert b["pending_since"] == NOW and p.read_bytes() == przed and _resztki(tmp_path) == []
    stary = b["commit_id"]

    res = writeback.commit(con, "R", now=NOW)                 # ponowienie tego samego przebiegu
    assert len(res.applied) == 1 and res.commit_id != stary, res
    po = p.read_bytes()
    b1, b2 = _backupy(con)
    assert (b1["pending_since"], b1["unreplaced_at"]) == (None, NOW)

    ures = writeback.undo(con, stary, now=NOW)
    assert not ures.restored and not ures.failed and not ures.blocked, ures
    assert p.read_bytes() == po
    assert len(writeback.undo(con, res.commit_id, now=NOW).restored) == 1
    assert p.read_bytes() == przed
    con.close()


@pytest.mark.parametrize("fmt", ["fits", "xisf"])
@pytest.mark.parametrize("dalej", ["commit", "undo"])
def test_smierc_po_podmianie_rekoncyliacja_potwierdza(tmp_path, monkeypatch, fmt, dalej):
    """Proces ginie PO podmianie, przed potwierdzeniem backupu i re-synciem: plik niesie zmianę,
    baza nie. Następny commit albo cofnięcie tej lokacji najpierw rozstrzyga backup z dyskiem
    (nagłówek commitu → podmiana zaszła): re-sync, wpisy 'applied', backup potwierdzony. Commit
    melduje zapis potwierdzony z dysku, cofnięcie cofa jak zwykły commit."""
    con, p, lid = _baza(tmp_path, fmt)
    przed = p.read_bytes()
    hh_przed = _hh(con, lid)
    _smierc_po_podmianie(monkeypatch)
    with pytest.raises(_Smierc):
        writeback.commit(con, "R", now=NOW)
    monkeypatch.undo()
    (b,) = _backupy(con)
    assert b["pending_since"] == NOW and p.read_bytes() != przed and _hh(con, lid) == hh_przed
    assert _resztki(tmp_path) == []
    if dalej == "commit":
        res = writeback.commit(con, "R", now=NOW)
        (a,) = res.applied
        assert "potwierdzony z dysku" in a.reason, res
        assert _hh(con, lid) != hh_przed
        st = con.execute("SELECT status, reason FROM pending_changes WHERE run_id='R'").fetchone()
        assert st["status"] == "applied" and "potwierdzone z dysku" in st["reason"]
    else:
        ures = writeback.undo(con, b["commit_id"], now=NOW)
        assert len(ures.restored) == 1 and not ures.blocked, ures
        assert p.read_bytes() == przed
    assert _backupy(con)[0]["pending_since"] is None
    con.close()


def test_smierc_po_podmianie_karty_object_rekoncyliacja_gasi_nagrobek(tmp_path, monkeypatch):
    """Rekoncyliacja, która potwierdza podmianę karty `OBJECT`, gasi nagrobek ręki tą samą klingą
    i parą commit/plik co commit udany - cofnięcie commitu go odtworzy (AR-38)."""
    con, p, lid, fid, cos = _baza_z_nagrobkiem(tmp_path)
    hh = _hh(con, lid)
    repo.stage_pending(con, run_id="R", location_id=lid, keyword="OBJECT", idx=0, op="set",
                       old_value=None, new_value="NGC 7000", new_type="str", new_comment=None,
                       expected_header_hash=hh)
    _smierc_po_podmianie(monkeypatch)
    with pytest.raises(_Smierc):
        writeback.commit(con, "R", now=NOW)
    monkeypatch.undo()
    assert _stan_nagrobka(con, fid) == (None, "user_cleared", cos)    # nagrobek jeszcze żyje
    cid = _backupy(con)[0]["commit_id"]
    ures = writeback.undo(con, cid, now=NOW)
    assert len(ures.restored) == 1, ures
    assert _stan_nagrobka(con, fid) == (None, "user_cleared", cos)    # zgaszony i odtworzony
    assert con.execute("SELECT count(*) FROM event WHERE verb = 'object.tombstone_cleared'"
                       ).fetchone()[0] == 1
    assert fits.getheader(str(p))["OBJECT"] == "NGC6992"
    con.close()


def test_smierc_przed_podmiana_a_plik_zmieniony_poza_programem(tmp_path, monkeypatch):
    """Po przerwanym commicie plik zmienił się poza programem (nagłówek ani sprzed, ani po
    commicie): rekoncyliacja nie blokuje lokacji, a backup BEZ DOWODU WYKONANIA wypada ze zwykłego
    cofnięcia (`unreplaced_at`, bramka astra A3); ponowny commit odbija stęchły staging, jak dotąd."""
    con, p, lid = _baza(tmp_path, "fits")
    _smierc_przed_podmiana(monkeypatch)
    with pytest.raises(_Smierc):
        writeback.commit(con, "R", now=NOW)
    monkeypatch.undo()
    with fits.open(str(p), mode="update") as hdul:
        hdul[0].header["TELESCOP"] = "OBCY"
    res = writeback.commit(con, "R", now=NOW)
    assert len(res.blocked) == 1 and "header_hash mismatch" in res.blocked[0].reason, res
    (b,) = _backupy(con)
    assert (b["pending_since"], b["unreplaced_at"]) == (None, NOW)
    con.close()


def test_nierozstrzygniety_backup_nie_cofa_pozniejszego_commitu(tmp_path, monkeypatch):
    """A3: C1 przerwany przed podmianą, plik zmieniony poza programem (TELESCOP=OBCY), potem C2
    zapisuje TEN SAM nagłówek wynikowy co C1. Cofnięcie niewykonanego C1 nie ma czego cofać - plik
    zostaje z zapisem C2, a cofnięcie C2 działa. Falsyfikator: `replaced=None` bez `unreplaced_at` -
    kontrola `post_hash` C1 przechodzi i cofnięcie C1 cofa C2."""
    con, p, lid = _baza(tmp_path, "fits")
    przed = p.read_bytes()
    _smierc_przed_podmiana(monkeypatch)
    with pytest.raises(_Smierc):
        writeback.commit(con, "R", now=NOW)
    monkeypatch.undo()
    with fits.open(str(p), mode="update") as hdul:
        hdul[0].header["TELESCOP"] = "OBCY"
    _scan_in(con, p)                                       # baza zna obcą wersję
    _stage_teleskop(con, "R2", lid)                        # C2: TELESCOP=EQ6 od obcej wersji
    res2 = writeback.commit(con, "R2", now=NOW)
    assert len(res2.applied) == 1, res2
    b1, b2 = _backupy(con)
    assert con.execute("SELECT post_hash FROM header_backups WHERE id=?", (b1["id"],)).fetchone()[0] \
        == con.execute("SELECT post_hash FROM header_backups WHERE id=?", (b2["id"],)).fetchone()[0]
    po_c2 = p.read_bytes()
    ures = writeback.undo(con, b1["commit_id"], now=NOW)
    assert not ures.restored and not ures.failed, ures
    assert p.read_bytes() == po_c2
    assert len(writeback.undo(con, res2.commit_id, now=NOW).restored) == 1
    assert fits.getheader(str(p))["TELESCOP"] == "OBCY" and p.read_bytes() != przed
    con.close()


@pytest.mark.parametrize("fmt", ["fits", "xisf"])
def test_blad_po_udanej_podmianie_rekoncyliacja_opisuje_plik_po_commicie(tmp_path, monkeypatch,
                                                                          fmt):
    """A4: podmiana zaszła, klient dostał błąd → 'failed', backup niepotwierdzony, baza opisuje plik
    sprzed commitu. Następny commit tej lokacji rekoncyliuje: baza opisuje plik PO commicie, wpis
    stagingu 'applied', backup potwierdzony - w JEDNEJ transakcji z wjazdem rekordu. Dawniej klinga
    skanu zdejmowała `pending_since` w tej samej transakcji, CAS rekoncyliacji rzucał, cała
    transakcja szła do tyłu, a rekoncyliacja meldowała sukces."""
    con, p, lid = _baza(tmp_path, fmt)
    hh_przed = _hh(con, lid)
    prawdziwy = writeback._replace_file_w

    def _blad_po(path, tmp, kopia):
        prawdziwy(path, tmp, kopia)
        raise OSError(64, "nazwa sieciowa jest już niedostępna")
    monkeypatch.setattr(writeback, "_replace_file_w", _blad_po)
    res = writeback.commit(con, "R", now=NOW)
    monkeypatch.undo()
    assert len(res.failed) == 1 and _backupy(con)[0]["pending_since"] == NOW, res
    assert _hh(con, lid) == hh_przed
    po = writeback._post_hash(str(p))

    repo.stage_pending(con, run_id="R2", location_id=lid, keyword="IMAGETYP", idx=0, op="set",
                       old_value=None, new_value="Light", new_type="str", new_comment=None,
                       expected_header_hash=hh_przed)
    writeback.commit(con, "R2", now=NOW)                  # wejście lokacji = rekoncyliacja
    assert _hh(con, lid) == po                             # baza opisuje plik po commicie
    st = con.execute("SELECT status FROM pending_changes WHERE run_id='R'").fetchone()[0]
    assert st == "applied" and _backupy(con)[0]["pending_since"] is None
    con.close()


@pytest.mark.parametrize("smierc", ["przed", "po"])
def test_ponowny_staging_pod_tym_samym_run_id_nie_znika_jako_wykonany(tmp_path, monkeypatch,
                                                                       smierc):
    """A5: przerwany zapis, potem ponowny staging INNEJ wartości pod tym samym `run_id` (GUI czyści
    staging przebiegu i stawia nowy). Rekoncyliacja potwierdza wyłącznie wpisy przerwanej próby:
    nowa wartość albo trafia do pliku (śmierć przed podmianą), albo zostaje odbita jako stęchła
    (śmierć po podmianie - baza opisywała plik sprzed niej) - nigdy 'applied' bez zapisu."""
    con, p, lid = _baza(tmp_path, "fits")
    (_smierc_przed_podmiana if smierc == "przed" else _smierc_po_podmianie)(monkeypatch)
    with pytest.raises(_Smierc):
        writeback.commit(con, "R", now=NOW)
    monkeypatch.undo()
    repo.clear_pending_for_run(con, "R")
    _stage_teleskop(con, "R", lid, value="EQ7")
    res = writeback.commit(con, "R", now=NOW)
    st = con.execute("SELECT status FROM pending_changes WHERE run_id='R'").fetchone()[0]
    teleskop = fits.getheader(str(p))["TELESCOP"]
    if smierc == "przed":
        assert len(res.applied) == 1 and st == "applied" and teleskop == "EQ7", res
    else:
        assert st == "blocked" and teleskop == "EQ6", res
    con.close()


def test_migracja_0030_kolumna_backupu_niepotwierdzonego(tmp_path):
    """0030 na bazie v29 z backupem: kolumna wchodzi PUSTA, wiersz nietknięty."""
    con = db.connect(str(tmp_path / "h.db"))
    for wersja, plik in db.MIGRATIONS:
        if wersja <= 29:
            db._apply_migration(con, wersja, db._migration_sql(plik))
    con.execute("PRAGMA foreign_keys = OFF")              # wiersz backupu bez lokacji - sam DDL
    con.execute("INSERT INTO commits(run_id, applied_at, summary) VALUES ('R', ?, 'x')", (NOW,))
    con.execute("INSERT INTO header_backups(commit_id, location_id, hdu_index, header_text, "
                "post_hash) VALUES (1, 1, 0, 'tekst', 'abc')")
    con.commit()
    assert db.migrate(con) == 30
    row = con.execute("SELECT header_text, post_hash, pending_since, unreplaced_at "
                      "FROM header_backups").fetchone()
    assert tuple(row) == ("tekst", "abc", None, None)
    con.close()


# ============================================================ AR-56: kompensacja renamu


def _rename_jeden(tmp_path):
    from test_rename import _jeden_plik
    return _jeden_plik(tmp_path)


def _pad_relokacji_raz(monkeypatch):
    prawdziwa = repo._apply_relocation
    stan = {"raz": True}

    def _f(*a, **kw):
        if stan["raz"]:
            stan["raz"] = False
            raise sqlite3.OperationalError("disk I/O error")
        return prawdziwa(*a, **kw)
    monkeypatch.setattr(repo, "_apply_relocation", _f)


def _drugi_proces(tmp_path):
    con2 = db.open_db(str(tmp_path / "z.db"))
    con2.execute("PRAGMA busy_timeout = 50")
    return con2


def test_kompensacja_renamu_uszeregowana_z_rekoncyliacja_innego_procesu(tmp_path, monkeypatch):
    """AR-56: transakcja przepięcia padła po `os.rename`, a w chwili powrotu pliku rekoncyliacja
    innego procesu próbuje przepiąć bazę na nową nazwę. Kompensacja trzyma blokadę zapisu bazy od
    odczytu do zgaszenia zamiaru, więc rekoncyliacja nie wchodzi (baza zajęta) - plik i baza zgodne
    pod starą nazwą, zamiar zgaszony. Falsyfikator: odczyt `path` i powrót pliku poza jedną
    transakcją - rekoncyliacja przepina bazę na nową nazwę, a plik wraca pod starą."""
    con, lid, stara, nowa = _rename_jeden(tmp_path)
    _pad_relokacji_raz(monkeypatch)
    con2 = _drugi_proces(tmp_path)
    prawdziwy = writeback.rename_file
    wtracenie = {}

    def _rename(src, dst):
        if src == nowa and dst == stara:                  # powrót pliku = kompensacja
            wtracenie["wynik"] = writeback.reconcile_renames(con2, now=NOW)
        return prawdziwy(src, dst)
    monkeypatch.setattr(writeback, "rename_file", _rename)
    res = writeback.commit_renames(con, "R", now=NOW)
    (w,) = wtracenie["wynik"]
    assert w.status == "blocked", w                        # baza zajęta przez kompensację
    assert len(res.failed) == 1 and "wrócił" in res.failed[0].reason, res
    assert os.path.exists(stara) and not os.path.exists(nowa)
    loc = con.execute("SELECT path FROM location WHERE id=?", (lid,)).fetchone()[0]
    zam = con.execute("SELECT in_flight FROM pending_renames").fetchone()[0]
    assert (loc, zam) == (stara, None)
    con2.close()
    con.close()


def test_rekoncyliacja_nie_przepina_po_kompensacji_innego_procesu(tmp_path, monkeypatch):
    """Druga połowa AR-56: rekoncyliacja widzi plik pod nową nazwą, a zanim weźmie blokadę bazy,
    kompensacja innego procesu oddaje plik pod starą nazwę i gasi zamiar. Pod blokadą zamiar nie
    jest już otwarty (i plik nie stoi tam, gdzie go widziała) → zero zapisu, 'blocked'; baza i plik
    zgodne pod starą nazwą. Falsyfikator: `settle_rename_intent` bez `expect_in_flight`/`potwierdz`
    - baza przepięta na nową nazwę, plik pod starą."""
    con, lid, stara, nowa = _rename_jeden(tmp_path)
    (r,) = writeback.renames_for_run(con, "R")
    repo.open_rename_intent(con, rename_id=r["id"], direction="commit")
    os.rename(stara, nowa)                                 # przerwana próba: plik pod nową nazwą
    con.execute("UPDATE location SET file_sha1 = NULL WHERE id = ?", (lid,))
    con.commit()
    con2 = db.open_db(str(tmp_path / "z.db"))
    prawdziwy = scan._mtime_iso
    stan = {"raz": True}

    def _mtime(st):
        wynik = prawdziwy(st)
        if stan["raz"]:                                   # kompensacja innego procesu w oknie
            stan["raz"] = False
            os.rename(nowa, stara)
            repo.drop_rename_intent(con2, rename_id=r["id"])
        return wynik
    monkeypatch.setattr(scan, "_mtime_iso", _mtime)
    (w,) = writeback.reconcile_renames(con, now=NOW)
    monkeypatch.undo()
    assert w.status == "blocked" and "inny proces" in w.reason, w
    loc = con.execute("SELECT path FROM location WHERE id=?", (lid,)).fetchone()[0]
    assert loc == stara and os.path.exists(stara) and not os.path.exists(nowa)
    con2.close()
    con.close()
