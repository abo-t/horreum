"""STRAŻNIK GENERACJI ZAPISU W MIEJSCU w skanie - dwa ogony paczki „warunki wsadu":

  * `AR-31` (1): podmiana treści pod znaną ścieżką wyłaniała klatkę OSOBNĄ transakcją przed
    strażnikiem przepięcia (`repo.rebind_location`). Odmowa `StaleScanRecord` zostawiała klatkę, a
    ponowienie widziało ją jako istniejącą i nie nagrywało zeznania - klatka bez `header`. Bliźniak
    w tym samym szwie: derywacja osi pisała kamerę przed wstępnym sprawdzeniem generacji;
  * `AR-17` (8): sterowniki klasyfikowały odczyt (nieczytelny / inny `IMAGETYP` / tożsamość /
    odcisk) PRZED strażnikiem generacji - rozdarty odczyt z zapisu w miejscu innego procesu dawał
    fałszywy raport przebiegu. Teraz sprawdzenie stoi zaraz po odczycie i prowadzi do ponowienia.

Operację zapisu w miejscu wstrzykuje monkeypatch (wiersz `inplace_op` w fazie `synced`, jak
`test_warunki_wsadu`), rozdarty odczyt - rekord podmieniony przy pierwszym odczycie. Każdy test
bez poprawki pada."""

from __future__ import annotations

import dataclasses

import pytest

from horreum import db, repo, scan

from test_copy_facts import _operacja
from test_orphan_testimony import _cls, _lpro, _zniknij
from test_scan import _stack
from test_writeback_inplace import NOW, _bez_faktow, _fits, _loc, _scan_in, _xisf


def _lid(con, path):
    return con.execute("SELECT id FROM location WHERE path = ?", (str(path),)).fetchone()[0]


def _zapis_po_wstepnym_sprawdzeniu(monkeypatch, con, path):
    """Podmienia `repo.newer_inplace_op`: przy PIERWSZYM pytaniu o lokację `path` oddaje prawdziwą
    odpowiedź, a zaraz po niej w dzienniku staje zakończona operacja zapisu w miejscu tej lokacji -
    czyli zapis z innego procesu między wstępnym sprawdzeniem generacji a transakcją klingi.
    Zwraca listę pytań (dowód, że wstrzyknięcie zaszło)."""
    prawdziwa = repo.newer_inplace_op
    lid = _lid(con, path)
    pytania = []

    def _przeplot(con_, *, location_id, op_id):
        wynik = prawdziwa(con_, location_id=location_id, op_id=op_id)
        if location_id == lid:
            pytania.append(op_id)
            if len(pytania) == 1:
                _operacja(con, lid, "synced")
        return wynik
    monkeypatch.setattr(repo, "newer_inplace_op", _przeplot)
    return pytania


def _bez_zeznania(con):
    return con.execute("SELECT count(*) FROM frame f WHERE NOT EXISTS "
                       "(SELECT 1 FROM header h WHERE h.frame_id = f.id)").fetchone()[0]


# ============================================================ AR-31 (1) podmiana jedną transakcją


def test_podmiana_po_odmowie_strazniaka_ponowienie_nagrywa_zeznanie(tmp_path, monkeypatch):
    """Plik pod znaną ścieżką dostaje nowe dane (podmiana treści). Zapis w miejscu z innego procesu
    wchodzi po wstępnym sprawdzeniu generacji, więc odmawia dopiero klinga przepięcia. Dawniej nowa
    klatka zostawała z pierwszej próby, ponowienie widziało `created=False` i nie nagrywało zeznania.
    Teraz odmowa cofa także klatkę, a ponowienie wyłania ją od nowa razem z zeznaniem."""
    kat = tmp_path / "arch"
    kat.mkdir()
    p = _fits(kat / "a.fits")
    con = db.open_db(str(tmp_path / "h.db"))
    scan.scan_tree(con, str(kat), volume="?", now=NOW)
    _fits(p, seed=1)                                        # nowe dane = nowa tożsamość
    pytania = _zapis_po_wstepnym_sprawdzeniu(monkeypatch, con, p)
    s = scan.scan_tree(con, str(kat), volume="?", now=NOW)
    monkeypatch.undo()
    assert len(pytania) == 2, pytania                       # odmowa i jedno ponowienie
    assert (s.isolated, s.frames_new, s.locations_rebound, s.headers) == (0, 1, 1, 1), s
    assert con.execute("SELECT count(*) FROM frame").fetchone()[0] == 2
    assert _bez_zeznania(con) == 0
    assert con.execute("SELECT f.sha1_data FROM location l JOIN frame f ON f.id = l.frame_id"
                       ).fetchone()[0] == scan.scan_file(str(p)).sha1_data
    con.close()


def test_odmowa_przepiecia_cofa_nowa_klatke(tmp_path, monkeypatch):
    """Ta sama odmowa widziana z `ingest_record` bez sterownika: `StaleScanRecord` nie zostawia
    w bazie ani nowej klatki, ani przepięcia, ani zdarzenia `frame.observed` - nic, co następna
    próba (także w kolejnym przebiegu) wzięłaby za już wyłonione."""
    p = _fits(tmp_path / "a.fits")
    con = db.open_db(str(tmp_path / "h.db"))
    _scan_in(con, p)
    stara = _loc(con, p)["frame_id"]
    _fits(p, seed=1)
    gen = repo.inplace_generation(con)
    _zapis_po_wstepnym_sprawdzeniu(monkeypatch, con, p)
    with pytest.raises(repo.StaleScanRecord):
        scan.ingest_record(con, scan.scan_file(str(p)), volume="V", now=NOW,
                           summary=scan.ScanSummary(), inplace_gen=gen)
    monkeypatch.undo()
    assert con.execute("SELECT count(*) FROM frame").fetchone()[0] == 1
    assert _loc(con, p)["frame_id"] == stara
    assert con.execute("SELECT count(*) FROM event WHERE verb = 'frame.observed'").fetchone()[0] == 1
    con.close()


def test_odmowa_generacji_przed_derywacja_osi_nie_zostawia_kamery(tmp_path):
    """Bliźniak w tym samym szwie: `ingest_record` wyprowadzał osie (`repo.upsert_camera`) PRZED
    wstępnym sprawdzeniem generacji, więc odczyt odrzucony jako stęchły zostawiał kamerę z nagłówka,
    który mógł być rozdarty. Teraz znana lokacja z nowszą operacją odmawia przed każdym zapisem."""
    p = _fits(tmp_path / "a.fits")
    con = db.open_db(str(tmp_path / "h.db"))
    _scan_in(con, p)
    assert con.execute("SELECT count(*) FROM camera").fetchone()[0] == 0
    _fits(p, extra=(("INSTRUME", "ZWO ASI2600MM Pro"), ("XPIXSZ", 3.76)))
    gen = repo.inplace_generation(con)
    _operacja(con, _lid(con, p), "synced")                  # zapis w miejscu po generacji
    with pytest.raises(repo.StaleScanRecord):
        scan.ingest_record(con, scan.scan_file(str(p)), volume="V", now=NOW,
                           summary=scan.ScanSummary(), inplace_gen=gen)
    assert con.execute("SELECT count(*) FROM camera").fetchone()[0] == 0
    con.close()


# ============================================================ AR-17 (8) strażnik zaraz po odczycie


def _rozdarty_pierwszy_odczyt(monkeypatch, con, path, rozdarcie):
    """Podmienia `scan.scan_file`: PIERWSZY odczyt `path` trafia w zapis w miejscu z innego procesu -
    w dzienniku staje operacja tej lokacji, a odczyt oddaje rekord rozdarty (`rozdarcie(rec)`).
    Kolejne odczyty - prawdziwe. Zwraca listę odczytów."""
    prawdziwa = scan.scan_file
    odczyty = []

    def _przeplot(sciezka, *a, **kw):
        rec = prawdziwa(sciezka, *a, **kw)
        if str(sciezka) == str(path):
            odczyty.append(1)
            if len(odczyty) == 1:
                _operacja(con, _lid(con, path), "synced")
                return rozdarcie(rec)
        return rec
    monkeypatch.setattr(scan, "scan_file", _przeplot)
    return odczyty


def _nieczytelny(rec):
    return dataclasses.replace(rec, header=None, cards=None, header_hash=None,
                               error="ParseError: nagłówek rozdarty", error_kind="parse")


def _inny_rodzaj(rec):
    return dataclasses.replace(rec, header={**rec.header, "IMAGETYP": "Light"})


@pytest.mark.parametrize("rozdarcie", [_nieczytelny, _inny_rodzaj], ids=["nieczytelny", "rodzaj"])
def test_skan_stosow_rozdarty_odczyt_nie_jest_odrzuceniem(tmp_path, monkeypatch, rozdarcie):
    """Droga „Stosy": odczyt rozdarty zapisem w miejscu dawniej szedł prosto do klasyfikacji -
    „nagłówek nieczytelny" albo „zeznaje inny rodzaj" w raporcie o zdrowym stacku. Teraz strażnik
    generacji zaraz po odczycie kieruje go do ponowienia, które wciąga plik."""
    t = tmp_path / "obrobka"
    t.mkdir()
    st = _stack(t / "masterLight_A.xisf", n=1)
    con = db.open_db(str(tmp_path / "h.db"))
    assert scan.scan_stacks(con, t, now=NOW).ingested == 1        # `volume='?'`: brama wyłączona
    odczyty = _rozdarty_pierwszy_odczyt(monkeypatch, con, st, rozdarcie)
    s = scan.scan_stacks(con, t, now=NOW)
    monkeypatch.undo()
    assert len(odczyty) == 2, odczyty
    assert (s.rejected_unreadable, s.rejected_kind, s.rejected_paths) == (0, 0, []), s
    assert (s.ingested, s.skipped, s.failed) == (1, 0, 0), s
    con.close()


def _inna_tozsamosc(rec):
    return dataclasses.replace(rec, sha1_data="0" * 40)


def _inny_odcisk(rec):
    return dataclasses.replace(rec, header_hash="0" * 40)


@pytest.mark.parametrize("rozdarcie", [_nieczytelny, _inna_tozsamosc, _inny_odcisk],
                         ids=["failed", "identity", "stale"])
def test_przejecie_zeznania_rozdarty_odczyt_nie_jest_werdyktem(tmp_path, monkeypatch, rozdarcie):
    """Przejęcie zeznania: werdykty `failed` / `identity` / `stale` zapadały na odczycie sprzed
    strażnika generacji. Rozdarty odczyt ocalałej kopii dawał więc fałszywy powód odmowy. Teraz
    strażnik stoi przed klasyfikacją, a ponowienie przejmuje zeznanie."""
    root = tmp_path / "ARCH"
    a, b = _lpro(root), _cls(root)
    con = db.open_db(str(tmp_path / "h.db"))
    scan.scan_tree(con, root, volume="?", now=NOW)
    _zniknij(con, a)
    odczyty = _rozdarty_pierwszy_odczyt(monkeypatch, con, b, rozdarcie)
    s = scan.adopt_orphan_testimony(con, now=NOW)
    monkeypatch.undo()
    assert len(odczyty) == 2 and s.read == 1, (odczyty, s)
    assert (s.adopted, s.failed, s.identity, s.stale, s.raced) == (1, 0, 0, 0, 0), s
    assert con.execute("SELECT filter_raw FROM header").fetchone()[0] == "CLS"
    con.close()


def test_uzupelnienie_faktow_kopii_rozdarty_naglowek_nie_jest_porazka(tmp_path, monkeypatch):
    """Bliźniak w uzupełnieniu faktów kopii: parser, który trafił nagłówek rozdarty zapisem
    w miejscu, rzucał, a sterownik liczył to jako `failed` o zdrowym pliku. Teraz przy operacji
    nowszej niż generacja idzie ponowienie, a plik liczy się jako przeczytany raz."""
    p = _xisf(tmp_path / "c.xisf")
    con = db.open_db(str(tmp_path / "h.db"))
    _scan_in(con, p)
    _bez_faktow(con, p)
    prawdziwa = scan._read_meta
    odczyty = []

    def _przeplot(sciezka, *a, **kw):
        if str(sciezka) == str(p):
            odczyty.append(1)
            if len(odczyty) == 1:
                _operacja(con, _lid(con, p), "synced")
                raise ValueError("nagłówek rozdarty")
        return prawdziwa(sciezka, *a, **kw)
    monkeypatch.setattr(scan, "_read_meta", _przeplot)
    s = scan.backfill_copy_facts(con, now=NOW)
    monkeypatch.undo()
    assert len(odczyty) == 2, odczyty
    assert (s.read, s.written, s.failed, s.stale, s.remaining) == (1, 1, 0, 0, 0), s
    con.close()
