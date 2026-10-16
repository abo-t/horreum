"""Cofnięcie commitu drogą ATOMOWĄ ze śladem własnego wyniku (AR-182, migracja 0044 `atomic_undo`).

Co pilnujemy: ślad wyniku (para odcisków: sha1 pliku i nagłówka, plik zastany, nazwy plików do
sprzątnięcia - AR-127) ZATWIERDZONY w bazie przed podmianą; ponowienie rozpoznaje własny wynik
WYŁĄCZNIE parą odcisków jednego śladu - także po zmianie poza nagłówkiem od commitu, po drodze
semantycznej i przy backupie tekstowym - a plik inny niż wynik i inny niż plik sprzed commitu nie jest
„już cofnięty”; szybka ścieżka „już cofnięte” bez odczytu pliku, gdy baza wciągnęła wynik własny
i `mtime` pliku jest tym z bazy; oznaczenie wciągnięcia dotyczy dokładnie jednego śladu. Pliki
prawdziwe (astropy, XISF z dwoma obrazami) w `tmp_path`."""
from __future__ import annotations

import dataclasses
import hashlib
import os
import sqlite3

import pytest
from astropy.io import fits

from horreum import db, repo, scan, writeback
from test_powody_pisarza import _fits_dwa_hdu
from test_writeback_inplace import (NOW, _baza_z_plikiem, _fits, _scan_in, _stary_commit, _xisf,
                                    _xisf_dwa_obrazy)


class _Smierc(BaseException):
    """Śmierć procesu w oknie - nie `Exception`, więc pisarz jej nie łapie."""


def _sha(p):
    return hashlib.sha1(open(p, "rb").read()).hexdigest()


def _slady(con):
    return [dict(r) for r in con.execute("SELECT * FROM atomic_undo ORDER BY id")]


def _fakty(con):
    return tuple(con.execute("SELECT l.header_hash, l.file_sha1, l.mtime, l.frame_id, "
                             "(SELECT count(*) FROM frame) FROM location l").fetchone())


def _kod(fr):
    return getattr(fr.reason, "code", None)


def _wewnetrzny(fr):
    return getattr(dict(fr.reason.params).get("inner"), "code", None)


def _plik(tmp_path, rodzaj):
    """`(ścieżka, zmiana)` - `zmiana(p)` zmienia bajt POZA nagłówkiem i przesuwa `mtime` o 2 s."""
    if rodzaj == "fits":
        p = _fits(tmp_path / "a.fits")

        def _offset(sciezka):
            with fits.open(str(sciezka), memmap=False) as hdul:
                return hdul.fileinfo(0)["datLoc"]
    elif rodzaj == "xisf":
        p = _xisf(tmp_path / "a.xisf")
        _offset = None
    elif rodzaj == "fits2hdu":
        p = _fits_dwa_hdu(tmp_path / "d.fits")

        def _offset(sciezka):
            return sciezka.read_bytes().index(b"'aaaa ") + 1
    else:
        p, stale = _xisf_dwa_obrazy(tmp_path / "x.xisf")

        def _offset(sciezka):
            return stale

    def _zmiana(sciezka):
        st = os.stat(sciezka)
        i = _offset(sciezka)
        with open(sciezka, "r+b") as fh:
            fh.seek(i)
            b = fh.read(1)
            fh.seek(i)
            fh.write(bytes([b[0] ^ 0x03]))
        os.utime(sciezka, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))
    return p, _zmiana


def _commit(tmp_path, rodzaj):
    """Plik po commicie drogą atomową: `(con, p, zmiana, commit_id, N = bajty po commicie)`."""
    p, zmiana = _plik(tmp_path, rodzaj)
    con, _ = _baza_z_plikiem(tmp_path, p)
    res = writeback.commit(con, "R", now=NOW)
    assert len(res.applied) == 1 and not res.in_place and res.commit_id is not None, res
    return con, p, zmiana, res.commit_id, p.read_bytes()


def _odczyty(monkeypatch):
    """Szpieg pełnych odczytów pliku w cofnięciu: skan (`scan_file`) i sha1 uchwytu/pliku."""
    licznik = []
    for modul, nazwa in ((scan, "scan_file"), (writeback, "_sha1_uchwytu"),
                         (writeback, "_sha1_pliku")):
        prawdziwa = getattr(modul, nazwa)

        def _szpieg(*a, _p=prawdziwa, _n=nazwa, **kw):
            licznik.append(_n)
            return _p(*a, **kw)
        monkeypatch.setattr(modul, nazwa, _szpieg)
    return licznik


# ============================================================ ślad przed podmianą


@pytest.mark.parametrize("rodzaj", ["fits", "xisf"])
def test_pierwsze_cofniecie_zostawia_zatwierdzony_slad_przed_podmiana(tmp_path, monkeypatch, rodzaj):
    """Pierwsze cofnięcie atomowe: jeden ślad - wynik (sha1, rozmiar, nagłówek) = plik po cofnięciu
    i para lokacji, źródło = wersja zapisana przez commit (N), kopia wyparta i plik tymczasowy
    sprzątnięte, `synced_at` w transakcji re-syncu. Ślad widać z DRUGIEGO połączenia w chwili wejścia
    do podmiany - jest zatwierdzony, nie tylko zapisany w transakcji wołającego.
    Falsyfikator: ślad po podmianie albo bez zatwierdzenia → drugie połączenie widzi 0 wierszy."""
    con, p, _zmiana, cid, n = _commit(tmp_path, rodzaj)
    prawdziwy = writeback._podmien
    widziane = []

    def _szpieg(*a, **kw):
        drugie = sqlite3.connect(str(tmp_path / "h.db"))
        widziane.append(drugie.execute("SELECT count(*) FROM atomic_undo").fetchone()[0])
        drugie.close()
        return prawdziwy(*a, **kw)
    monkeypatch.setattr(writeback, "_podmien", _szpieg)
    u = writeback.undo(con, cid, now=NOW)
    monkeypatch.undo()
    assert len(u.restored) == 1 and u.complete and widziane == [1], (u, widziane)
    (s,) = _slady(con)
    lok = con.execute("SELECT file_sha1, header_hash FROM location").fetchone()
    assert (s["result_sha1"], s["result_size"]) == (_sha(p), os.path.getsize(p))
    assert (s["result_sha1"], s["result_hash"]) == (lok["file_sha1"], lok["header_hash"])
    assert s["byte_exact"] == 1
    assert (s["source_sha1"], s["source_size"]) == (hashlib.sha1(n).hexdigest(), len(n))
    assert s["displaced_path"].endswith(writeback._KOPIA_SUFFIX)
    assert not os.path.exists(s["displaced_path"]) and not os.path.exists(s["prepared_path"])
    assert not os.path.exists(writeback._nazwa_zwrotna(s["displaced_path"]))
    assert (s["recorded_at"], s["synced_at"]) == (NOW, NOW)
    con.close()


def test_slad_w_otwartej_transakcji_to_blad_wolajacego(tmp_path):
    """Ślad, który nie byłby zatwierdzony przed podmianą (otwarta transakcja, zakres `atomic`), to
    błąd wołającego - zero zapisu. Falsyfikator: zdejmij EXPECT z `record_atomic_undo` - wiersz
    wchodzi (a `with con` zatwierdza transakcję wołającego w połowie)."""
    con, p, _zmiana, cid, _n = _commit(tmp_path, "fits")
    b = con.execute("SELECT id FROM header_backups").fetchone()[0]
    s = "a" * 40
    pola = dict(backup_id=b, result_sha1=s, result_size=1, result_hash=s, byte_exact=True,
                source_sha1=s, source_size=1, displaced_path="k", prepared_path="t", now=NOW)
    with pytest.raises(ValueError):
        with repo.atomic(con):
            repo.record_atomic_undo(con, **pola)
    con.execute("UPDATE location SET mtime = mtime")              # transakcja otwarta DML-em
    with pytest.raises(ValueError):
        repo.record_atomic_undo(con, **pola)
    con.rollback()
    assert _slady(con) == []
    con.close()


def test_smierc_miedzy_sladem_a_podmiana_ponowienie_cofa_i_oznacza_jeden_slad(tmp_path,
                                                                              monkeypatch):
    """Proces ginie po zatwierdzeniu śladu, przed podmianą: plik = N, ślad bez `synced_at` (nigdy
    nie zgodzi się z plikiem). Ponowienie cofa od nowa - drugi ślad z TYM SAMYM wynikiem, oznaczony
    on, nie starsza próba; ponowne oznaczenie najnowszego pasującego śladu nic nie zmienia.
    Falsyfikator: wybór śladu do oznaczenia spośród jeszcze nieoznaczonych → starsza próba
    oznaczona drugim wołaniem."""
    con, p, _zmiana, cid, n = _commit(tmp_path, "fits2hdu")

    def _smierc(*a, **kw):
        raise _Smierc()
    monkeypatch.setattr(writeback, "_podmien", _smierc)
    with pytest.raises(_Smierc):
        writeback.undo(con, cid, now=NOW)
    monkeypatch.undo()
    (s1,) = _slady(con)
    assert p.read_bytes() == n and s1["synced_at"] is None
    u = writeback.undo(con, cid, now=NOW)
    assert len(u.restored) == 1 and u.complete, u
    s1, s2 = _slady(con)
    assert (s1["result_sha1"], s1["result_hash"]) == (s2["result_sha1"], s2["result_hash"])
    assert (s1["synced_at"], s2["synced_at"]) == (None, NOW)
    b = s2["backup_id"]
    najnowszy = writeback._slad_pary(con, b, s2["result_sha1"], s2["result_hash"])
    assert najnowszy == s2["id"]
    assert repo.mark_atomic_undo_synced(con, undo_id=najnowszy, now="2026-10-17") is False
    assert [s["synced_at"] for s in _slady(con)] == [None, NOW]
    ponowione = writeback.undo(con, cid, now=NOW)
    assert [_kod(f) for f in ponowione.already] == ["undo_already_own"], ponowione
    assert [s["synced_at"] for s in _slady(con)] == [None, NOW]
    con.close()


@pytest.mark.parametrize("rodzaj", ["fits2hdu", "xisf2"])
def test_smierc_po_podmianie_ponowienie_rozpoznaje_wlasny_wynik(tmp_path, monkeypatch, rodzaj):
    """Plik zmieniony poza nagłówkiem od commitu, cofnięcie podmienia plik i proces ginie przed
    re-synciem: pod ścieżką wynik inny niż plik sprzed commitu, ślad bez `synced_at`. Ponowienie
    rozpoznaje własny wynik parą odcisków i dokańcza samą synchronizację (obietnica
    `undo_resync_failed` prawdziwa). Falsyfikator: ślad po podmianie → ponowienie bez śladu odmawia
    (`undo_region_unproven`)."""
    con, p, zmiana, cid, _n = _commit(tmp_path, rodzaj)
    zmiana(p)
    prawdziwy = writeback._podmien

    def _f(*a, **kw):
        prawdziwy(*a, **kw)
        raise _Smierc()
    monkeypatch.setattr(writeback, "_podmien", _f)
    with pytest.raises(_Smierc):
        writeback.undo(con, cid, now=NOW)
    monkeypatch.undo()
    (s,) = _slady(con)
    assert s["synced_at"] is None and s["byte_exact"] == 0 and _sha(p) == s["result_sha1"]
    u = writeback.undo(con, cid, now=NOW)
    assert [_kod(f) for f in u.restored] == ["undo_sync_finished"] and u.complete, u
    assert _slady(con)[0]["synced_at"] == NOW
    assert con.execute("SELECT file_sha1 FROM location").fetchone()[0] == _sha(p)
    con.close()


# ============================================================ zmiana od commitu i ponowienie


@pytest.mark.parametrize("zmieniony", [True, False], ids=["zmiana_od_commitu", "bez_zmiany"])
@pytest.mark.parametrize("rodzaj", ["fits2hdu", "xisf2"])
def test_pierwsze_cofniecie_nazywa_zmiane_od_commitu(tmp_path, rodzaj, zmieniony):
    """Plik zmieniony poza nagłówkiem od commitu (sha1 ≠ wersja zapisana przez commit) - cofnięcie
    idzie, nagłówek wraca, zmiana zostaje w pliku, powód to mówi (`undo_outside_changed`, w
    `semantic`), ślad niesie źródło inne niż N. Bez zmiany - zwykłe cofnięcie bajtowe bez powodu.
    Falsyfikator: orkiestracja bez `expect_file_sha1` → `undo_semantic_outside`."""
    con, p, zmiana, cid, n = _commit(tmp_path, rodzaj)
    if zmieniony:
        zmiana(p)
    zastany = p.read_bytes()
    u = writeback.undo(con, cid, now=NOW)
    (r,) = u.restored
    (s,) = _slady(con)
    assert s["source_sha1"] == hashlib.sha1(zastany).hexdigest()
    if zmieniony:
        assert _kod(r) == "undo_outside_changed" and u.semantic == [r], u
        assert s["byte_exact"] == 0 and s["source_sha1"] != hashlib.sha1(n).hexdigest()
        assert p.read_bytes()[len(zastany) // 2:] == zastany[len(zastany) // 2:]  # zmiana została
    else:
        assert r.reason is None and not u.semantic and s["byte_exact"] == 1, u
    assert u.complete and s["synced_at"] == NOW
    con.close()


@pytest.mark.parametrize("resync", ["padl", "przeszedl"])
def test_ponowienie_po_cofnieciu_ze_zmiana_od_commitu_domyka(tmp_path, monkeypatch, resync):
    """Ponowienie po cofnięciu bajtowym z wynikiem innym niż plik sprzed commitu: drugie HDU zmienione
    od commitu karty `OBJECT` (nagrobek ręki zgaszony commitem). Re-sync padł: pierwsze
    `undo_resync_failed`, ponowienie dokańcza
    synchronizację z dowodem wyniku własnego; przeszedł: `undo_outside_changed`, ponowienie „już
    cofnięte” wynikiem własnym. Trzecie zawsze „już cofnięte”; nagrobek odtworzony RAZ.
    Falsyfikator: kontrola bez wyników własnych → ponowienie po padniętym re-syncu odmawia."""
    p = _fits_dwa_hdu(tmp_path / "d.fits")
    con = db.open_db(str(tmp_path / "h.db"))
    _scan_in(con, p)
    lok = con.execute("SELECT id, frame_id, header_hash FROM location").fetchone()
    repo.user_assign_object(con, alias_norm=None, canon="COS", catalog=None, kind="own",
                            frame_ids=[lok["frame_id"]], now=NOW)
    repo.clear_object_assignment(con, frame_ids=[lok["frame_id"]], now=NOW)
    repo.stage_pending(con, run_id="R", location_id=lok["id"], keyword="OBJECT", idx=0, op="set",
                       old_value=None, new_value="NGC 7000", new_type="str", new_comment=None,
                       expected_header_hash=lok["header_hash"])
    res = writeback.commit(con, "R", now=NOW)
    assert len(res.applied) == 1 and not res.in_place, res
    dane = bytearray(p.read_bytes())
    i = dane.index(b"'aaaa ")
    dane[i:i + 5] = b"'bbbb"
    p.write_bytes(bytes(dane))

    def _odtworzone():
        return con.execute("SELECT count(*) FROM event WHERE verb = 'object.tombstone_restored'"
                           ).fetchone()[0]
    if resync == "padl":
        monkeypatch.setattr(writeback.scan, "scan_file",
                            lambda path, **kw: (_ for _ in ()).throw(OSError(64, "zerwany udział")))
    u1 = writeback.undo(con, res.commit_id, now=NOW)
    monkeypatch.undo()
    u2 = writeback.undo(con, res.commit_id, now=NOW)
    u3 = writeback.undo(con, res.commit_id, now=NOW)
    if resync == "padl":
        assert [_kod(f) for f in u1.failed] == ["undo_resync_failed"] and not u1.complete, u1
        assert [_kod(f) for f in u2.restored] == ["undo_sync_finished"] and u2.complete, u2
    else:
        assert [_kod(f) for f in u1.restored] == ["undo_outside_changed"] and u1.complete, u1
        assert [_kod(f) for f in u2.already] == ["undo_already_own"] and u2.complete, u2
    assert [_kod(f) for f in u3.already] == ["undo_already_own"] and u3.complete, u3
    assert b"'bbbb" in p.read_bytes() and fits.getheader(str(p))["OBJECT"] == "NGC6992"
    assert _odtworzone() == 1
    con.close()


# ============================================================ szybka ścieżka i jej granica


@pytest.mark.parametrize("rodzaj", ["fits", "xisf"])
def test_ponowienie_po_domknietym_cofnieciu_nie_czyta_pliku(tmp_path, monkeypatch, rodzaj):
    """Baza wciągnęła wynik własny (ślad z `synced_at`, para lokacji = para śladu), `mtime` pliku
    ten z bazy → „już cofnięte” wynikiem własnym BEZ pełnego odczytu pliku, cofnięcie domknięte.
    Falsyfikator: szybka ścieżka zdjęta (`synced_at` ignorowane) → dowód czyta plik."""
    con, p, _zmiana, cid, _n = _commit(tmp_path, rodzaj)
    assert writeback.undo(con, cid, now=NOW).complete
    odczyty = _odczyty(monkeypatch)
    u = writeback.undo(con, cid, now=NOW)
    monkeypatch.undo()
    assert [_kod(f) for f in u.already] == ["undo_already_own"] and u.complete, u
    assert odczyty == [], odczyty
    con.close()


@pytest.mark.parametrize("skan", [False, True], ids=["bez_skanu", "po_skanie"])
def test_zmiana_po_wlasnym_cofnieciu_z_nowym_mtime_nie_jest_juz_cofnieta(tmp_path, skan):
    """Po domkniętym cofnięciu drugie HDU zmienione z NOWYM `mtime` (± skan, który wyrównuje bazę):
    ani szybka ścieżka, ani dowód - blokada z receptą skanu, niedomknięte, plik i baza nietknięte.
    Falsyfikator: szybka ścieżka bez pary `location.file_sha1`/`header_hash` (sam nagłówek i `mtime`)
    → po skanie „już cofnięte”."""
    con, p, zmiana, cid, _n = _commit(tmp_path, "fits2hdu")
    assert writeback.undo(con, cid, now=NOW).complete
    zmiana(p)
    if skan:
        _scan_in(con, p)
    bajty, fakty = p.read_bytes(), _fakty(con)
    u = writeback.undo(con, cid, now=NOW)
    (fr,) = u.blocked
    assert not u.already and not u.complete and not u.restored, u
    assert _kod(fr) == "undo_region_unproven" and _wewnetrzny(fr) == "check_outside_changed"
    assert p.read_bytes() == bajty and _fakty(con) == fakty
    con.close()


# ============================================================ powrót spoza Horreum (dowód kotwicy)


@pytest.mark.parametrize("skan", [False, True], ids=["baza_po_commicie", "po_skanie"])
@pytest.mark.parametrize("rodzaj", ["fits", "fits2hdu", "xisf2"])
def test_powrot_spoza_horreum_ze_zmiana_obok_naglowka_wymaga_dowodu(tmp_path, rodzaj, skan):
    """Plik po commicie atomowym wraca z zewnątrz do bajtów sprzed commitu, ale z bajtem zmienionym
    poza nagłówkiem (dane głównego HDU, drugie HDU, drugi obraz XISF), bez śladu własnego cofnięcia:
    ani re-sync, ani „już cofnięte” - blokada, plik i baza nietknięte (dawniej `restored` - zmiana
    wjeżdżała jako cofnięta). Po skanie kotwicą dalej jest koperta, nie mutowalna lokacja.
    Falsyfikator: gałąź atomowa „plik = backup” bez dowodu całego pliku albo kotwica z
    `location.file_sha1`."""
    p, zmiana = _plik(tmp_path, rodzaj)
    przed = p.read_bytes()
    con, _ = _baza_z_plikiem(tmp_path, p)
    res = writeback.commit(con, "R", now=NOW)
    assert len(res.applied) == 1 and not res.in_place, res
    p.write_bytes(przed)
    zmiana(p)
    if skan:
        _scan_in(con, p)
    bajty, fakty = p.read_bytes(), _fakty(con)
    u = writeback.undo(con, res.commit_id, now=NOW)
    (fr,) = u.blocked
    assert not u.restored and not u.failed and not u.already and not u.complete, u
    assert _kod(fr) == "undo_region_unproven", fr.reason
    assert p.read_bytes() == bajty and _fakty(con) == fakty and _slady(con) == []
    con.close()


@pytest.mark.parametrize("skan", [False, True], ids=["baza_po_commicie", "po_skanie"])
def test_wierny_powrot_spoza_horreum_domyka_dowodem_calego_pliku(tmp_path, monkeypatch, skan):
    """Plik wraca z zewnątrz DOKŁADNIE do bajtów sprzed commitu: baza po commicie → re-sync z dowodem
    (`undo_sync_finished`); po skanie → „już cofnięte” z dowodem całego pliku (`undo_already`,
    zdanie „cały plik i baza”), jednym pełnym odczytem. Falsyfikator: dowód zdjęty → 0 odczytów."""
    p = _fits(tmp_path / "a.fits")
    przed = p.read_bytes()
    con, _ = _baza_z_plikiem(tmp_path, p)
    res = writeback.commit(con, "R", now=NOW)
    p.write_bytes(przed)
    if skan:
        _scan_in(con, p)
    odczyty = _odczyty(monkeypatch)
    u = writeback.undo(con, res.commit_id, now=NOW)
    monkeypatch.undo()
    assert u.complete and p.read_bytes() == przed, u
    if skan:
        assert [_kod(f) for f in u.already] == ["undo_already"], u
        assert str(u.already[0].reason) == "już cofnięte - cały plik i baza opisują stan sprzed commitu"
    else:
        assert [_kod(f) for f in u.restored] == ["undo_sync_finished"], u
    assert odczyty == ["scan_file"], odczyty
    con.close()


# ============================================================ droga semantyczna i backup tekstowy


def test_droga_semantyczna_fits_utrwala_zrodlo_i_wynik_strumienia(tmp_path, monkeypatch):
    """Droga semantyczna FITS (`_plan_przywrocenia` → None): wynik liczony strumieniem zapisu pliku
    tymczasowego, źródło pełnym odczytem uchwytu blokady - para śladu = para lokacji po re-syncu,
    ślad wciągnięty. Falsyfikator: brak sha1 źródła na tej drodze → ślad odbity (NOT NULL),
    cofnięcie `undo_record_not_saved`; zły sha1 wyniku → ślad bez `synced_at`."""
    con, p, _zmiana, cid, n = _commit(tmp_path, "fits2hdu")
    monkeypatch.setattr(writeback, "_plan_przywrocenia", lambda *a, **kw: None)
    u = writeback.undo(con, cid, now=NOW)
    monkeypatch.undo()
    (r,) = u.restored
    assert _kod(r) == "undo_semantic" and u.complete, u
    (s,) = _slady(con)
    lok = con.execute("SELECT file_sha1, header_hash FROM location").fetchone()
    assert (s["result_sha1"], s["result_hash"]) == (lok["file_sha1"], lok["header_hash"])
    assert s["source_sha1"] == hashlib.sha1(n).hexdigest() and s["byte_exact"] == 0
    assert s["synced_at"] == NOW
    con.close()


def test_wynik_semantyczny_z_innym_regionem_rozpoznany_po_naglowku(tmp_path, monkeypatch):
    """XISF z niezerowym wypełnieniem: cofnięcie semantyczne (inne adresy bloków - wymuszone) oddaje
    zera w miejscu wypełnienia, które XML zwolnił, więc region na dysku ≠ region koperty; re-sync
    padł. Ponowienie rozpoznaje plik NAGŁÓWKIEM wyniku ze śladu i dokańcza synchronizację.
    Falsyfikator: kandydat tylko po bajtach regionu → ponowienie idzie do pisarza i odbija się od
    nagłówka (`undo_header_changed`)."""
    p = _xisf(tmp_path / "w.xisf", wypelnienie=b"\x20")
    przed = p.read_bytes()
    con, _ = _baza_z_plikiem(tmp_path, p)
    res = writeback.commit(con, "R", now=NOW)
    env = writeback.RegionBackup.decode(
        con.execute("SELECT header_text FROM header_backups").fetchone()[0])
    monkeypatch.setattr(writeback, "_plan_przywrocenia", lambda *a, **kw: None)
    monkeypatch.setattr(writeback.scan, "scan_file",
                        lambda path, **kw: (_ for _ in ()).throw(OSError(64, "zerwany udział")))
    u1 = writeback.undo(con, res.commit_id, now=NOW)
    monkeypatch.undo()
    assert [_kod(f) for f in u1.failed] == ["undo_resync_failed"], u1
    assert p.read_bytes()[:len(env.region)] != env.region and p.read_bytes() != przed
    u2 = writeback.undo(con, res.commit_id, now=NOW)
    assert [_kod(f) for f in u2.restored] == ["undo_sync_finished"] and u2.complete, u2
    assert _slady(con)[0]["synced_at"] == NOW
    con.close()


def test_backup_tekstowy_slad_domyka_a_zmiana_po_nim_odmawia(tmp_path):
    """Commit sprzed kopert (backup tekstowy - bez kotwicy pliku): pierwsze cofnięcie (semantyczne)
    zostawia ślad, ponowienie - „już cofnięte” wynikiem własnym. Plik zmieniony potem poza
    nagłówkiem nie jest ani wynikiem, ani do dowiedzenia - blokada `undo_own_unproven`, baza
    nietknięta. Falsyfikator: backup tekstowy ze śladem w gałęzi dawnej → zmiana wjeżdża re-synciem."""
    p = _fits_dwa_hdu(tmp_path / "s.fits")
    con = db.open_db(str(tmp_path / "h.db"))
    _scan_in(con, p)
    cid = _stary_commit(con, p, "NGC 6992")
    u1 = writeback.undo(con, cid, now=NOW)
    assert len(u1.restored) == 1 and u1.semantic and u1.complete, u1
    u2 = writeback.undo(con, cid, now=NOW)
    assert [_kod(f) for f in u2.already] == ["undo_already_own"] and u2.complete, u2
    st = os.stat(p)
    dane = bytearray(p.read_bytes())
    i = dane.index(b"'aaaa ")
    dane[i:i + 5] = b"'bbbb"
    p.write_bytes(bytes(dane))
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))
    bajty, fakty = p.read_bytes(), _fakty(con)
    u3 = writeback.undo(con, cid, now=NOW)
    (fr,) = u3.blocked
    assert _kod(fr) == "undo_own_unproven" and _wewnetrzny(fr) == "check_no_anchor", fr.reason
    assert not u3.complete and p.read_bytes() == bajty and _fakty(con) == fakty
    con.close()


def test_backup_tekstowy_bez_sladu_mowi_ze_reszty_pliku_nie_sprawdzono(tmp_path):
    """Backup tekstowy cofnięty poza tą drogą (powrót pliku sprzed commitu z zewnątrz + skan, bez
    śladu): „już cofnięte” jak dawniej, ale zdaniem, które mówi, czego nie sprawdzono
    (`undo_already_text`). Falsyfikator: zdanie „cały plik i baza” (`undo_already`) dla backupu
    bez odcisku pliku."""
    p = _fits(tmp_path / "s.fits")
    przed = p.read_bytes()
    con = db.open_db(str(tmp_path / "h.db"))
    _scan_in(con, p)
    cid = _stary_commit(con, p, "NGC 6992")
    p.write_bytes(przed)
    _scan_in(con, p)
    u = writeback.undo(con, cid, now=NOW)
    assert [_kod(f) for f in u.already] == ["undo_already_text"] and u.complete, u
    assert _slady(con) == []
    con.close()


# ============================================================ re-sync pierwszego cofnięcia i ślad


@pytest.mark.parametrize("rodzaj", ["fits2hdu", "xisf2"])
def test_slad_nie_powstal_plik_nietkniety(tmp_path, monkeypatch, rodzaj):
    """Ślad nie wszedł do bazy (zajęta baza): 'failed' `undo_record_not_saved` ze szczegółem, plik
    bajtowo po commicie, bez pliku tymczasowego i kopii, baza nietknięta. Falsyfikator: porażka
    śladu połknięta → plik podmieniony bez śladu."""
    con, p, _zmiana, cid, n = _commit(tmp_path, rodzaj)
    fakty = _fakty(con)

    def _zajeta(*a, **kw):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(repo, "record_atomic_undo", _zajeta)
    u = writeback.undo(con, cid, now=NOW)
    monkeypatch.undo()
    (fr,) = u.failed
    assert _kod(fr) == "undo_record_not_saved" and dict(fr.reason.params)["detail"], fr.reason
    assert p.read_bytes() == n and _fakty(con) == fakty and _slady(con) == []
    zostalo = [x.name for x in tmp_path.iterdir()
               if x.name.endswith(".tmp") or x.name.endswith(writeback._KOPIA_SUFFIX)]
    assert zostalo == [], zostalo
    con.close()


def test_zmiana_miedzy_podmiana_a_resynciem_nie_wjezdza(tmp_path, monkeypatch):
    """Re-sync pierwszego cofnięcia wciąga WYŁĄCZNIE wynik tego cofnięcia (para śladu) albo plik
    sprzed commitu: bajt drugiego HDU zmieniony tuż po podmianie → 'failed' z werdyktem kontroli,
    baza dalej po commicie, ślad bez `synced_at`; ponowienie - blokada z receptą skanu.
    Falsyfikator: re-sync po podmianie bez kontroli → `restored` z cudzą zmianą w bazie."""
    con, p, zmiana, cid, _n = _commit(tmp_path, "fits2hdu")
    naglowek = con.execute("SELECT header_hash FROM location").fetchone()[0]
    prawdziwy = writeback._podmien

    def _f(*a, **kw):
        wynik = prawdziwy(*a, **kw)
        zmiana(p)
        return wynik
    monkeypatch.setattr(writeback, "_podmien", _f)
    u = writeback.undo(con, cid, now=NOW)
    monkeypatch.undo()
    (fr,) = u.failed
    assert _kod(fr) == "check_outside_changed" and not u.complete, u
    assert con.execute("SELECT header_hash FROM location").fetchone()[0] == naglowek
    assert _slady(con)[0]["synced_at"] is None
    u2 = writeback.undo(con, cid, now=NOW)
    assert [_kod(f) for f in u2.blocked] == ["undo_region_unproven"] and not u2.complete, u2
    con.close()


def test_powrot_obcej_wersji_w_oknie_cofniecia_idzie_pod_kopie_wyliczona_ze_sladu(tmp_path,
                                                                                monkeypatch):
    """Inny pisarz zmienia plik w oknie podmiany cofnięcia: jego wersja wraca pod ścieżkę, a nasza
    idzie pod kopię ZWROTNĄ o nazwie wyliczonej z kopii wypartej utrwalonej w śladzie
    (`_nazwa_zwrotna`) - ślad zna wszystkie pliki, które cofnięcie może zostawić (AR-127). Wynik
    'blocked', ślad bez `synced_at`. Falsyfikator: losowa nazwa kopii zwrotnej w `_oddaj_wyparty`."""
    con, p, zmiana, cid, _n = _commit(tmp_path, "fits2hdu")
    prawdziwa = writeback._replace_file_w
    wolania = []

    def _replace(dst, src, kopia):
        wolania.append((str(dst), str(src), str(kopia)))
        if len(wolania) == 1:
            zmiana(p)                                  # cudzy zapis tuż przed podmianą
        prawdziwa(dst, src, kopia)
    monkeypatch.setattr(writeback, "_replace_file_w", _replace)
    u = writeback.undo(con, cid, now=NOW)
    monkeypatch.undo()
    (fr,) = u.blocked
    assert _kod(fr) == "other_writer_returned" and not u.complete, u
    (s,) = _slady(con)
    assert s["synced_at"] is None and len(wolania) == 2, wolania
    assert wolania[0][2] == s["displaced_path"]
    assert wolania[1] == (str(p), s["displaced_path"], writeback._nazwa_zwrotna(s["displaced_path"]))
    assert b"'aaaa " not in p.read_bytes()             # pod ścieżką wersja innego pisarza
    con.close()


def test_para_odciskow_niezgodna_nie_jest_wynikiem_wlasnym(tmp_path):
    """Dowód „plik = wynik własny” to PARA `(file_sha1, header_hash)` jednego śladu: rekord złożony
    z sha1 wyniku i nagłówka innej wersji (rozdarty odczyt) nie przechodzi, rekord z pełną parą -
    tak. Falsyfikator: zbiór samych sha1 → rekord rozdarty przechodzi."""
    p = _fits(tmp_path / "a.fits")
    rec = scan.scan_file(str(p))
    para = (rec.file_sha1, rec.header_hash)
    kontrola = writeback._KontrolaDanych(0, None, None, "0" * 40, frozenset({para}))
    assert writeback._kontrola_danych(rec, None, kontrola) is None
    rozdarty = dataclasses.replace(rec, header_hash="1" * 40)
    assert writeback._kontrola_danych(rozdarty, None, kontrola).code == "check_header_other"


def test_wycofany_resync_wycofuje_tez_oznaczenie_sladu(tmp_path, monkeypatch):
    """Oznaczenie wciągnięcia idzie w TRANSAKCJI re-syncu: błąd po nim wycofuje razem wjazd rekordu
    i `synced_at` - baza dalej po commicie, ślad bez `synced_at`; ponowienie dokańcza oba.
    Falsyfikator: oznaczenie we własnej, zatwierdzanej transakcji → `synced_at` przy bazie po
    commicie."""
    con, p, _zmiana, cid, _n = _commit(tmp_path, "fits")
    naglowek = con.execute("SELECT header_hash FROM location").fetchone()[0]
    prawdziwe = repo.mark_atomic_undo_synced

    def _pada(*a, **kw):
        prawdziwe(*a, **kw)
        raise sqlite3.OperationalError("disk I/O error")
    monkeypatch.setattr(repo, "mark_atomic_undo_synced", _pada)
    u = writeback.undo(con, cid, now=NOW)
    monkeypatch.undo()
    assert [_kod(f) for f in u.failed] == ["undo_resync_failed"], u
    assert con.execute("SELECT header_hash FROM location").fetchone()[0] == naglowek
    assert _slady(con)[0]["synced_at"] is None
    u2 = writeback.undo(con, cid, now=NOW)
    assert [_kod(f) for f in u2.restored] == ["undo_sync_finished"] and u2.complete, u2
    assert _slady(con)[0]["synced_at"] == NOW
    con.close()
