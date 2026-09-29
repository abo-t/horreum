"""WARUNKI WSADU pisarza w miejscu (`AR-17` (4)-(7)) - szwy rdzenia poza pilotażem:

  (4) import z dawcy podaje klindze generację zapisu w miejscu (dyscyplina skanu);
  (5) rename lokacji idzie pod strażą relokacji - bramka izolacji i generacji powtórzona
      w transakcji, która obejmuje `os.rename` i przepięcie `location.path`;
  (6) odzysk operacji OTWARTEJ z nieudaną kontrolą danych ma tę samą drogę powrotu co `written`;
  (7) sterowniki czytające pliki kopii ponawiają RAZ odczyt odrzucony przez strażnika generacji.

Pliki syntetyczne w `tmp_path` (bateria hermetyczna). Każdy test bez poprawki pada."""

from __future__ import annotations

import hashlib
import json

import pytest

from horreum import db, repo, scan, writeback
from horreum.import_fitsmirror import ImportAbort, open_donor, run_import

from test_copy_facts import _operacja
from test_import_fitsmirror import L_RC8_MM, _mk_donor
from test_orphan_testimony import _cls, _lpro, _zniknij
from test_scan import _stack
from test_writeback_inplace import (
    NOW, _baza_z_plikiem, _bez_faktow, _commit_z_padem_resyncu, _fits, _fits_dwa_hdu, _hash, _loc,
    _operacje, _otwarta_operacja, _scan_in, _xisf,
)


# ============================================================ (4) import z generacją zapisu


def test_import_odrzuca_lokacje_zapisana_w_miejscu_w_trakcie(tmp_path):
    """W trakcie importu równoległy skan zakłada lokację pliku, którego import jeszcze nie doszedł,
    a pisarz zapisuje ją w miejscu (`synced`, nowy nagłówek w bazie). Rekord importu to zeznanie
    dawcy sprzed zapisu: dawniej `ingest_record` bez generacji wciągał je na lokację opisaną już po
    zapisie (stary `header_hash` wracał do bazy). Teraz generacja sprzed pre-flightu odrzuca rekord
    (`StaleScanRecord`) → `ImportAbort`, baza zostaje przy fakcie po zapisie."""
    donor_path, pliki = _mk_donor(tmp_path, [("LIGHTS/a.fits", L_RC8_MM, 1),
                                             ("LIGHTS/b.fits", L_RC8_MM, 2)])
    b = pliki["LIGHTS/b.fits"][0]
    donor = open_donor(donor_path)
    con = db.open_db(str(tmp_path / "horreum.db"))
    stan = {}

    def _rownolegly_pisarz(done, _total, _path):
        if done != 1:
            return
        vol = con.execute("SELECT volume FROM location").fetchone()[0]
        scan.ingest_record(con, scan.scan_file(str(b)), volume=vol, now=NOW,
                           summary=scan.ScanSummary())
        lb = _loc(con, b)
        repo.stage_pending(con, run_id="R", location_id=lb["id"], keyword="OBJECT", idx=0,
                           op="set", old_value=None, new_value="M 31", new_type="str",
                           new_comment=None, expected_header_hash=lb["header_hash"])
        assert len(writeback.commit(con, "R", now=NOW, inplace=True).in_place) == 1
        stan["po_zapisie"] = _loc(con, b)["header_hash"]
        assert stan["po_zapisie"] == _hash(b) != lb["header_hash"]

    with pytest.raises(ImportAbort, match="zapis w miejscu"):
        run_import(donor, con, now=NOW, rng_seed=1, progress=_rownolegly_pisarz)
    assert _loc(con, b)["header_hash"] == stan["po_zapisie"]
    con.close()
    donor.close()


# ============================================================ (5) rename pod strażą relokacji


@pytest.mark.parametrize("faza", ["written", "synced"])
def test_rename_po_bramce_izolacji_odbija_zapis_w_miejscu(tmp_path, monkeypatch, faza):
    """Rename przeszedł bramkę izolacji; zanim zrobił `os.rename`, zapis w miejscu tego pliku
    otworzył operację i został `written` (izolowana) albo `synced` (nagłówek, z którego pochodzi
    nazwa, zmieniony). Dawniej rename przenosił plik i przepinał lokację. Teraz bramka i generacja
    powtórzone pod blokadą bazy w transakcji relokacji → 'blocked', plik nietknięty pod starą
    nazwą, baza bez `location.renamed`."""
    p = _fits(tmp_path / "b.fits")
    con, loc = _baza_z_plikiem(tmp_path, p)                 # przebieg "R" = zapis w miejscu
    nowa = tmp_path / "nowa.fits"
    repo.stage_rename(con, run_id="N", location_id=loc["id"], old_path=str(p),
                      new_path=str(nowa),
                      expected_mtime=con.execute("SELECT mtime FROM location WHERE id = ?",
                                                 (loc["id"],)).fetchone()[0])
    prawdziwa = repo.isolating_inplace_op
    stan = {"raz": True}

    def _przeplot(con_, location_id):
        wynik = prawdziwa(con_, location_id)                # bramka renamu: jeszcze czysto
        if stan["raz"]:
            stan["raz"] = False
            if faza == "written":
                _commit_z_padem_resyncu(monkeypatch, con, "R")
            else:
                assert len(writeback.commit(con, "R", now=NOW, inplace=True).in_place) == 1
            stan["po_zapisie"] = p.read_bytes()
        return wynik
    monkeypatch.setattr(repo, "isolating_inplace_op", _przeplot)
    rn = writeback.commit_renames(con, "N", now=NOW)
    monkeypatch.undo()
    op_id = _operacje(con)[0]["id"]
    assert not rn.applied and len(rn.blocked) == 1, rn
    assert f"operacja {op_id}" in rn.blocked[0].reason
    assert p.read_bytes() == stan["po_zapisie"] and not nowa.exists()
    assert _loc(con, p)["id"] == loc["id"]
    assert con.execute("SELECT count(*) FROM event WHERE verb = 'location.renamed'"
                       ).fetchone()[0] == 0
    assert [r["status"] for r in writeback.renames_for_run(con, "N")] == ["blocked"]
    con.close()


def test_rename_pod_straza_przepina_lokacje_w_tej_samej_transakcji(tmp_path):
    """Bez zapisu w miejscu rename przechodzi: plik pod nową nazwą, `location.path` przepięta
    jednym zdarzeniem `location.renamed`; odmowa prymitywu (cel zajęty na dysku) nie zostawia
    w bazie ani przepięcia, ani zdarzenia."""
    p = _fits(tmp_path / "c.fits")
    q = _fits(tmp_path / "d.fits", seed=3)
    con = db.open_db(str(tmp_path / "h.db"))
    _scan_in(con, p)
    _scan_in(con, q)
    lp, lq = _loc(con, p), _loc(con, q)
    mtime = lambda lid: con.execute("SELECT mtime FROM location WHERE id = ?",   # noqa: E731
                                    (lid,)).fetchone()[0]
    nowa = tmp_path / "nowa.fits"
    (tmp_path / "zajety.fits").write_bytes(b"x")
    repo.stage_rename(con, run_id="N", location_id=lp["id"], old_path=str(p), new_path=str(nowa),
                      expected_mtime=mtime(lp["id"]))
    repo.stage_rename(con, run_id="N", location_id=lq["id"], old_path=str(q),
                      new_path=str(tmp_path / "zajety.fits"), expected_mtime=mtime(lq["id"]))
    rn = writeback.commit_renames(con, "N", now=NOW)
    assert [f.path for f in rn.applied] == [str(nowa)] and len(rn.blocked) == 1, rn
    assert nowa.exists() and not p.exists() and q.exists()
    assert con.execute("SELECT path FROM location WHERE id = ?", (lp["id"],)).fetchone()[0] == \
        str(nowa)
    assert con.execute("SELECT path FROM location WHERE id = ?", (lq["id"],)).fetchone()[0] == str(q)
    assert con.execute("SELECT count(*) FROM event WHERE verb = 'location.renamed'"
                       ).fetchone()[0] == 1
    con.close()


# ============================================================ (6) odzysk operacji otwartej


def test_odzysk_operacji_otwartej_z_danymi_zmienionymi_wraca_do_skanu(tmp_path, monkeypatch):
    """Operacja OTWARTA (`unverified`), a dane poza nagłówkiem podmienione na dysku. Dawniej odzysk
    przywracał region, kontrola danych nie przechodziła i operacja zostawała otwarta z jedynym
    wyjściem `release_inplace_op` - każde ponowienie powtarzało tę samą niezgodność. Teraz ta sama
    droga powrotu co z `written`: plik ze STARYM nagłówkiem (podmienione dane zostają - tego powrót
    nie ukrywa), faza `recovered` z powodem, wpis stagingu 'failed', `location.mtime` NULL,
    a następny skan czyta plik w całości i opisuje go od nowa."""
    kat = tmp_path / "arch"
    kat.mkdir()
    p, zly = _fits_dwa_hdu(kat / "d.fits")
    con, op, przed = _otwarta_operacja(tmp_path, monkeypatch, p)
    assert op["phase"] == "unverified" and scan._isolated(con, str(p))
    dane = bytearray(p.read_bytes())
    dane[zly] ^= 0xFF                                       # podmiana danych poza nagłówkiem
    p.write_bytes(bytes(dane))
    oczekiwany = bytearray(przed)
    oczekiwany[zly] ^= 0xFF

    w = writeback.recover_torn(con, op["id"], now=NOW)
    assert w.status == "restored" and "poza nagłówkiem" in w.reason and "przeskanuj" in w.reason, w
    assert p.read_bytes() == bytes(oczekiwany)
    assert _operacje(con)[0]["phase"] == "recovered" and not scan._isolated(con, str(p))
    assert con.execute("SELECT mtime FROM location").fetchone()[0] is None
    (wpis,) = writeback.pending_for_run(con, "R")
    assert wpis["status"] == "failed" and "przeskanuj" in wpis["reason"]
    ev = con.execute("SELECT payload FROM event WHERE verb = 'location.writeback_reverted'"
                     ).fetchone()
    assert json.loads(ev[0])["phase_before"] == "unverified"
    assert writeback.recover_torn(con, op["id"], now=NOW).status == "blocked"   # zamknięta

    s = scan.scan_tree(con, str(kat), volume="V", now=NOW)
    assert (s.isolated, s.skipped, s.locations_refreshed) == (0, 0, 1), s
    assert con.execute("SELECT file_sha1 FROM location").fetchone()[0] == hashlib.sha1(
        bytes(oczekiwany)).hexdigest()
    con.close()


def test_powrot_operacji_otwartej_trzyma_cas_fazy(tmp_path, monkeypatch):
    """Klinga powrotu przyjmuje wyłącznie fazę izolującą przeczytaną pod blokadą: inna faza
    w bazie (drugi proces zdążył ją zmienić) albo faza nieizolująca → `ValueError`, zero zapisu."""
    p, _ = _fits_dwa_hdu(tmp_path / "c.fits")
    con, op, _ = _otwarta_operacja(tmp_path, monkeypatch, p)
    for faza in ("written", "synced"):
        with pytest.raises(ValueError):
            repo.revert_inplace_op(con, op_id=op["id"], now=NOW, reason="r", expect_phase=faza)
    assert _operacje(con)[0]["phase"] == "unverified"
    assert con.execute("SELECT mtime FROM location").fetchone()[0] is not None
    con.close()


# ============================================================ (7) jedno ponowienie po konflikcie generacji


def _konflikt_przed_odczytem(monkeypatch, con, nazwa, path, ile):
    """Podmienia `scan.<nazwa>`: przy pierwszych `ile` odczytach pliku `path` tuż PRZED odczytem
    w dzienniku staje operacja zapisu w miejscu tej lokacji, już ZAKOŃCZONA (`synced`) - czyli
    operacja zakończona między generacją sterownika a odczytem pliku. Plik niczego nie zmienia, więc
    jedyną przyczyną odmowy jest strażnik generacji. Zwraca listę odczytów pliku (dowód, że
    ponowienie jest jedno, a nie pętla)."""
    prawdziwa = getattr(scan, nazwa)
    odczyty = []

    def _przeplot(sciezka, *a, **kw):
        if str(sciezka) == str(path):
            odczyty.append(1)
            if len(odczyty) <= ile:
                lid = con.execute("SELECT id FROM location WHERE path = ?",
                                  (str(path),)).fetchone()[0]
                _operacja(con, lid, "synced")
        return prawdziwa(sciezka, *a, **kw)
    monkeypatch.setattr(scan, nazwa, _przeplot)
    return odczyty


# (konflikty, zapis): jeden konflikt → ponowienie zapisuje; trzy dostępne → dwie próby, kubełek.
_PRZYPADKI = [(1, True), (3, False)]


@pytest.mark.parametrize("konflikty, zapis", _PRZYPADKI)
def test_skan_drzewa_ponawia_raz(tmp_path, monkeypatch, konflikty, zapis):
    kat = tmp_path / "arch"
    kat.mkdir()
    p = _fits(kat / "a.fits")
    con = db.open_db(str(tmp_path / "h.db"))
    scan.scan_tree(con, str(kat), volume="?", now=NOW)
    przed = con.execute("SELECT header_hash FROM location").fetchone()[0]
    _fits(p, obj="M 42")                                    # ten sam obraz, inny nagłówek
    odczyty = _konflikt_przed_odczytem(monkeypatch, con, "scan_file", p, konflikty)
    s = scan.scan_tree(con, str(kat), volume="?", now=NOW)
    monkeypatch.undo()
    po = con.execute("SELECT header_hash FROM location").fetchone()[0]
    assert len(odczyty) == 2, odczyty
    if zapis:
        assert (s.isolated, s.headers_refreshed) == (0, 1) and po == _hash(p) != przed, s
    else:
        assert (s.isolated, s.isolated_paths, s.headers_refreshed) == (1, [str(p)], 0), s
        assert po == przed
    con.close()


@pytest.mark.parametrize("konflikty, zapis", _PRZYPADKI)
def test_uzupelnienie_xisf_ponawia_raz(tmp_path, monkeypatch, konflikty, zapis):
    p = _xisf(tmp_path / "a.xisf")
    con = db.open_db(str(tmp_path / "h.db"))
    _scan_in(con, p)
    _bez_faktow(con, p, bez_odcisku=True)
    odczyty = _konflikt_przed_odczytem(monkeypatch, con, "scan_file", p, konflikty)
    s = scan.backfill_xisf_headers(con, now=NOW)
    monkeypatch.undo()
    assert len(odczyty) == 2 and s.read == 1, (odczyty, s)
    if zapis:
        assert (s.failed, s.remaining) == (0, 0) and _loc(con, p)["header_hash"] == _hash(p), s
    else:
        assert (s.failed, s.remaining) == (1, 1) and "izolowana" in s.failed_paths[0], s
        assert _loc(con, p)["header_hash"] is None
    con.close()


@pytest.mark.parametrize("konflikty, zapis", _PRZYPADKI)
def test_uzupelnienie_faktow_kopii_ponawia_raz(tmp_path, monkeypatch, konflikty, zapis):
    p = _xisf(tmp_path / "c.xisf")
    con = db.open_db(str(tmp_path / "h.db"))
    _scan_in(con, p)
    _bez_faktow(con, p)
    odczyty = _konflikt_przed_odczytem(monkeypatch, con, "_read_meta", p, konflikty)
    s = scan.backfill_copy_facts(con, now=NOW)
    monkeypatch.undo()
    hdr = con.execute("SELECT hdr_hash FROM location").fetchone()[0]
    assert len(odczyty) == 2 and s.read == 1, (odczyty, s)
    if zapis:
        assert (s.written, s.stale, s.remaining) == (1, 0, 0) and hdr is not None, s
    else:
        assert (s.written, s.stale, s.stale_paths, s.remaining) == (0, 1, [str(p)], 1), s
        assert hdr is None
    con.close()


@pytest.mark.parametrize("konflikty, zapis", _PRZYPADKI)
def test_przejecie_zeznania_ponawia_raz(tmp_path, monkeypatch, konflikty, zapis):
    root = tmp_path / "ARCH"
    a, b = _lpro(root), _cls(root)
    con = db.open_db(str(tmp_path / "h.db"))
    scan.scan_tree(con, root, volume="?", now=NOW)
    _zniknij(con, a)
    odczyty = _konflikt_przed_odczytem(monkeypatch, con, "scan_file", b, konflikty)
    s = scan.adopt_orphan_testimony(con, now=NOW)
    monkeypatch.undo()
    filtr = con.execute("SELECT filter_raw FROM header").fetchone()[0]
    assert len(odczyty) == 2 and s.read == 1, (odczyty, s)
    if zapis:
        assert (s.adopted, s.raced, s.remaining) == (1, 0, 0) and filtr == "CLS", s
    else:
        assert (s.adopted, s.raced, s.remaining) == (0, 1, 1) and filtr == "L-Pro", s
    con.close()


@pytest.mark.parametrize("konflikty, zapis", _PRZYPADKI)
def test_skan_stosow_ponawia_raz(tmp_path, monkeypatch, konflikty, zapis):
    t = tmp_path / "obrobka"
    t.mkdir()
    st = _stack(t / "masterLight_A.xisf", n=1)
    con = db.open_db(str(tmp_path / "h.db"))
    assert scan.scan_stacks(con, t, now=NOW).ingested == 1        # `volume='?'`: brama wyłączona
    odczyty = _konflikt_przed_odczytem(monkeypatch, con, "scan_file", st, konflikty)
    s = scan.scan_stacks(con, t, now=NOW)
    monkeypatch.undo()
    assert len(odczyty) == 2, odczyty
    assert (s.ingested, s.skipped) == ((1, 0) if zapis else (0, 1)), s
    con.close()
