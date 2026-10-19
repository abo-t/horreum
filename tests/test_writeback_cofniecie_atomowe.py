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
import json
import os
import shutil
import sqlite3
import subprocess
import sys

import pytest
from astropy.io import fits

from horreum import db, repo, scan, writeback
from horreum.gui import queries
from horreum.item_reasons import PowodPozycji
from test_powody_pisarza import _fits_dwa_hdu
from test_writeback_inplace import (NOW, _baza_z_plikiem, _fits, _scan_in, _stage, _stary_commit,
                                    _xisf, _xisf_dwa_obrazy)


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


# ============================================================ backup tekstowy ze śladem przyjęty skanem (AR-229)


def _zmien_note(p, *, przesun=0, mtime=True):
    """Bajt wartości karty `NOTE` drugiego HDU (`_fits_dwa_hdu`) zmieniony - poza nagłówkiem, który
    czyta skan; `mtime` +2 s albo zachowany co do nanosekundy."""
    st = os.stat(p)
    dane = bytearray(p.read_bytes())
    i = dane.index(b"NOTE    = '") + 11 + przesun
    dane[i] ^= 0x03
    p.write_bytes(bytes(dane))
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + (2_000_000_000 if mtime else 0)))


def _tekstowy_ze_sladem(tmp_path, wariant):
    """Commit sprzed kopert (backup tekstowy) cofnięty raz drogą atomową - ślad wyniku R jest - a potem
    plik spoza Horreum, który nie jest wynikiem R i ma nagłówek sprzed commitu: `wierny_powrot` -
    bajty sprzed commitu A wracają (R ≠ A, bo drugie HDU zmieniło się przed pierwszym cofnięciem),
    `wynik_zmieniony` - R zmieniony poza nagłówkiem z nowym `mtime`, `wynik` - R nietknięty.
    `(con, p, cid)`."""
    p = _fits_dwa_hdu(tmp_path / "s.fits")
    przed = p.read_bytes()
    con = db.open_db(str(tmp_path / "h.db"))
    _scan_in(con, p)
    cid = _stary_commit(con, p, "NGC 6992")
    if wariant == "wierny_powrot":
        _zmien_note(p)
    u1 = writeback.undo(con, cid, now=NOW)
    assert len(u1.restored) == 1 and u1.complete and len(_slady(con)) == 1, u1
    if wariant == "wierny_powrot":
        st = os.stat(p)
        p.write_bytes(przed)
        os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))
        assert hashlib.sha1(przed).hexdigest() != _slady(con)[0]["result_sha1"]
    elif wariant == "wynik_zmieniony":
        _zmien_note(p)
    return con, p, cid


@pytest.mark.parametrize("wariant", ["wierny_powrot", "wynik_zmieniony"])
def test_backup_tekstowy_ze_sladem_skan_przyjmuje_plik(tmp_path, monkeypatch, wariant):
    """AR-229: backup tekstowy nie ma kotwicy całego pliku, więc pliku z nagłówkiem sprzed commitu,
    który nie jest wynikiem własnego cofnięcia, nie da się dowieść. Bez skanu - odmowa z receptą skanu
    (ponowienie to samo), plik i baza nietknięte. Po skanie, który przyjął ten plik (pełny sha1 pod
    blokadą == `location.file_sha1`) - „już cofnięte” zdaniem z granicą sprawdzenia, domknięte, jeden
    pełny odczyt; ponowienie to samo. Falsyfikator: gałąź akceptacji zdjęta → po skanie odmowa w kółko;
    akceptacja na samym braku kotwicy → „już cofnięte” bez skanu."""
    con, p, cid = _tekstowy_ze_sladem(tmp_path, wariant)
    bajty, fakty = p.read_bytes(), _fakty(con)
    for _ in range(2):
        u = writeback.undo(con, cid, now=NOW)
        (fr,) = u.blocked
        assert _kod(fr) == "undo_own_unproven" and _wewnetrzny(fr) == "check_no_anchor", fr.reason
        assert not u.already and not u.complete, u
        assert p.read_bytes() == bajty and _fakty(con) == fakty
    _scan_in(con, p)
    for _ in range(2):
        odczyty = _odczyty(monkeypatch)
        u = writeback.undo(con, cid, now=NOW)
        monkeypatch.undo()
        assert [_kod(f) for f in u.already] == ["undo_already_text"] and u.complete, u
        assert str(u.already[0].reason) == str(writeback._JUZ_TEKST)
        assert odczyty == ["scan_file"], odczyty
    assert p.read_bytes() == bajty
    con.close()


@pytest.mark.parametrize("mtime", [True, False], ids=["nowy_mtime", "ten_sam_mtime"])
def test_backup_tekstowy_przyjety_skanem_zmiana_po_skanie_odmawia(tmp_path, mtime):
    """AR-229: skan przyjął plik („już cofnięte”), potem drugie HDU zmienione jeszcze raz - z nowym albo
    z ZACHOWANYM `mtime` (nagłówek i `mtime` w bazie dalej się zgadzają). Pełny sha1 pod blokadą nie
    jest odciskiem, który baza przyjęła - odmowa, plik i baza nietknięte. Falsyfikator: akceptacja bez
    warunku `location.file_sha1` → przy zachowanym `mtime` „już cofnięte”."""
    con, p, cid = _tekstowy_ze_sladem(tmp_path, "wynik_zmieniony")
    _scan_in(con, p)
    assert writeback.undo(con, cid, now=NOW).complete
    _zmien_note(p, przesun=1, mtime=mtime)
    bajty, fakty = p.read_bytes(), _fakty(con)
    u = writeback.undo(con, cid, now=NOW)
    (fr,) = u.blocked
    assert _kod(fr) == "undo_own_unproven" and not u.already and not u.complete, u
    assert p.read_bytes() == bajty and _fakty(con) == fakty
    con.close()


def test_backup_tekstowy_wynik_zmieniony_z_zachowanym_mtime_po_pelnym_odczycie(tmp_path):
    """AR-229, granica: wynik własny zmieniony poza nagłówkiem z ZACHOWANYM `mtime`. Bez pełnego odczytu
    baza dalej opisuje wynik ze śladu - szybka ścieżka mówi „już cofnięte” wynikiem własnym bez
    czytania pliku (granica zaufania `mtime`, jak brama przyrostowa skanu, która takiego pliku też nie
    przeczyta). Gdy baza przeczyta plik w całości (`ingest_record` po pełnym odczycie), nagłówek jest
    sprzed commitu, a reszty backup tekstowy sprawdzić nie pozwala - „już cofnięte” zdaniem z tą granicą.
    Falsyfikator: gałąź akceptacji zdjęta → po pełnym odczycie odmowa."""
    con, p, cid = _tekstowy_ze_sladem(tmp_path, "wynik")
    _zmien_note(p, mtime=False)
    u = writeback.undo(con, cid, now=NOW)
    assert [_kod(f) for f in u.already] == ["undo_already_own"] and u.complete, u
    _scan_in(con, p)
    u = writeback.undo(con, cid, now=NOW)
    assert [_kod(f) for f in u.already] == ["undo_already_text"] and u.complete, u
    con.close()


def test_koperta_bez_kotwicy_poza_zakresem_akceptacji_skanem(tmp_path):
    """AR-229 dotyczy WYŁĄCZNIE backupu tekstowego: koperta bez sha1 pliku sprzed commitu (sprzed AR-19,
    commit atomowy - bez operacji w miejscu, więc i bez jej kotwicy) też nie ma kotwicy, ale skan jej
    nie domyka - odmowa o regionie zostaje. Falsyfikator: akceptacja bez warunku backupu tekstowego →
    „już cofnięte”."""
    p = _fits_dwa_hdu(tmp_path / "d.fits")
    con, _ = _baza_z_plikiem(tmp_path, p)
    res = writeback.commit(con, "R", now=NOW)
    assert len(res.applied) == 1 and not res.in_place, res
    b = con.execute("SELECT id, header_text FROM header_backups").fetchone()
    env = writeback.RegionBackup.decode(b["header_text"])
    stara = writeback.RegionBackup(env.fmt, env.offset, env.region, env.size, env.ino,
                                   env.pre_hash).encode()
    con.execute("UPDATE header_backups SET header_text = ? WHERE id = ?", (stara, b["id"]))
    con.commit()
    assert writeback.undo(con, res.commit_id, now=NOW).complete
    _zmien_note(p)
    _scan_in(con, p)
    u = writeback.undo(con, res.commit_id, now=NOW)
    (fr,) = u.blocked
    assert _kod(fr) == "undo_region_unproven" and _wewnetrzny(fr) == "check_no_anchor", fr.reason
    assert not u.already and not u.complete, u
    con.close()


# ============================================================ pliki obok ścieżki po przerwanym cofnięciu (AR-127)


def _kody(fr):
    """Kod powodu wyniku i kody jego dopisków (`notes`)."""
    if fr.reason is None:
        return []
    noty = dict(getattr(fr.reason, "params", ())).get("notes", ())
    return [getattr(fr.reason, "code", None), *(getattr(n, "code", None) for n in noty)]


def _sha_lub_brak(sciezka):
    return _sha(sciezka) if os.path.exists(sciezka) else None


def _nazwy(s):
    return writeback._nazwy_sladu(s["displaced_path"], s["prepared_path"])


def _werdykt(con, undo_id):
    w = con.execute("SELECT outcome, kept_paths, settled_at FROM atomic_undo WHERE id = ?",
                    (undo_id,)).fetchone()
    return w["outcome"], json.loads(w["kept_paths"]), w["settled_at"]


def _lokacja(con):
    return writeback._location(con, con.execute("SELECT id FROM location").fetchone()[0])


def _klatka(con):
    return con.execute("SELECT frame_id FROM location").fetchone()[0]


_DZIECKO = r'''
import json, os, sys
sys.path[:0] = json.loads(sys.argv[1])
from pathlib import Path
from horreum import writeback
from test_powody_pisarza import _fits_dwa_hdu
from test_writeback_inplace import NOW, _baza_z_plikiem
k, punkt = Path(sys.argv[2]), sys.argv[3]
p = _fits_dwa_hdu(k / "d.fits")
con, _ = _baza_z_plikiem(k, p)
res = writeback.commit(con, "R", now=NOW)
(k / "commit.txt").write_text(str(res.commit_id))
def _zgin(*a, **kw):
    os._exit(9)
if punkt == "przed_podmiana":
    writeback._podmien = _zgin
elif punkt == "po_podmianie":
    writeback._rozjazd_odcisku = _zgin
else:
    prawdziwa, wolania = writeback._replace_file_w, []
    def _replace(dst, src, kopia):
        wolania.append(1)
        if len(wolania) == 1:            # obcy zapis drugiego HDU tuż przed podmianą
            st = os.stat(p)
            dane = bytearray(p.read_bytes())
            dane[dane.index(b"NOTE    = '") + 11] ^= 0x03
            p.write_bytes(bytes(dane))
            os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))
        prawdziwa(dst, src, kopia)
    writeback._replace_file_w = _replace
    writeback._usun_kopie = _zgin        # pierwsze sprzątanie w tej drodze to kopia zwrotna Z
writeback.undo(con, res.commit_id, now=NOW)
os._exit(3)
'''


def _zgin_w_cofnieciu(tmp_path, punkt):
    """Prawdziwa śmierć procesu (`os._exit`, żaden `finally` nie sprząta) w oknie podmiany cofnięcia:
    commit drogą atomową i cofnięcie w procesie potomnym. Zwraca `commit_id`."""
    wynik = subprocess.run([sys.executable, "-c", _DZIECKO, json.dumps(sys.path), str(tmp_path), punkt],
                           capture_output=True, text=True, timeout=300)
    assert wynik.returncode == 9, (wynik.returncode, wynik.stderr[-2000:])
    return int((tmp_path / "commit.txt").read_text())


@pytest.mark.parametrize("punkt", ["przed_podmiana", "po_podmianie", "po_powrocie_do_z"])
def test_smierc_procesu_w_oknie_cofniecia_zostawia_pliki_do_oka(tmp_path, punkt):
    """Proces ginie w oknie podmiany cofnięcia (przed `ReplaceFileW` - zostaje T; po nim - K = plik
    zastany; po powrocie wersji innego pisarza - Z = wynik). Baza otwarta od nowa: pierwsze ponowienie
    - bramka widzi plik obok ścieżki, ślad dostaje `kept` z TRZEMA nazwami, cofnięcie raz zablokowane
    z powodem, wiersz Porządków; ani plik pod ścieżką, ani pliki obok nie zmieniają bajtu. Drugie
    ponowienie idzie zwykłą drogą (P zmienia się albo nie - wg stanu), resztki zostają do ręki
    człowieka, wiersz Porządków trwa. Falsyfikator: bramka zdjęta → pierwsze ponowienie domyka
    cofnięcie, a resztka zostaje niewidoczna (stan sprzed AR-127)."""
    cid = _zgin_w_cofnieciu(tmp_path, punkt)
    con = db.open_db(str(tmp_path / "h.db"))
    p = tmp_path / "d.fits"
    (s,) = _slady(con)
    nazwy = _nazwy(s)
    obok = {x: _sha_lub_brak(x) for x in nazwy}
    widoczne = [x for x in nazwy if obok[x] is not None]
    assert widoczne and s["settled_at"] is None, obok
    przed = _sha(p)
    u = writeback.undo(con, cid, now=NOW)
    (fr,) = u.blocked
    assert _kod(fr) == "undo_cut_kept" and not u.complete, u
    assert dict(fr.reason.params)["paths"] == widoczne
    assert _sha(p) == przed and {x: _sha_lub_brak(x) for x in nazwy} == obok
    assert _werdykt(con, s["id"]) == ("kept", list(nazwy), NOW)
    assert queries.kept_copy_frame_ids(con) == {_klatka(con)}
    u2 = writeback.undo(con, cid, now=NOW)
    assert u2.complete and len(u2.restored) == 1, u2
    assert (_sha(p) != przed) == (punkt != "po_podmianie")
    assert {x: _sha_lub_brak(x) for x in widoczne} == {x: obok[x] for x in widoczne}
    assert queries.kept_copy_frame_ids(con) == {_klatka(con)}
    con.close()


def _zywy_wlasciciel_przed_podmiana(tmp_path, monkeypatch):
    """Stan żywego właściciela tuż po zatwierdzeniu śladu: P = plik zastany, T = wynik, K i Z brak
    (atrapa śmierci w `_podmien` bez sprzątania T - jak po prawdziwej śmierci)."""
    con, p, _zmiana, cid, n = _commit(tmp_path, "fits2hdu")

    def _smierc(*a, **kw):
        raise _Smierc()
    monkeypatch.setattr(writeback, "_podmien", _smierc)
    monkeypatch.setattr(writeback, "_sprzatnij_tmp", lambda tmp, zachowaj: None)
    with pytest.raises(_Smierc):
        writeback.undo(con, cid, now=NOW)
    monkeypatch.undo()
    (s,) = _slady(con)
    return con, p, cid, s


def test_obserwator_w_przeplocie_z_zywym_wlascicielem_nie_pisze_clean(tmp_path, monkeypatch):
    """Przeplot obserwatora z żywym właścicielem: obserwator czyta K i Z (nie ma), właściciel w tym
    czasie podmienia plik (T → P, plik zastany → K), obserwator czyta T (nie ma), właściciel ginie
    przed sprzątnięciem K.
    Każdy odczyt był prawdziwy, a ich koniunkcja nigdy nie opisywała dysku - obserwator NIE pisze
    `clean`: ślad zostaje bez werdyktu, bramka przepuszcza; następny dotyk widzi K → `kept`, Porządki.
    Falsyfikator: obserwator zapisuje `clean` po trzech „nie ma” → K niewidoczna na zawsze."""
    con, p, cid, s = _zywy_wlasciciel_przed_podmiana(tmp_path, monkeypatch)
    k, _z, t = _nazwy(s)
    assert os.path.exists(t) and not os.path.exists(k)
    prawdziwa = scan.path_gone

    def _przeplot(x):
        if x == t:
            writeback._replace_file_w(str(p), t, k)
        return prawdziwa(x)
    monkeypatch.setattr(scan, "path_gone", _przeplot)
    assert writeback._rekoncyliuj_slady(con, _lokacja(con), now=NOW) is None
    monkeypatch.undo()
    assert _werdykt(con, s["id"]) == (None, [], None)
    assert os.path.exists(k) and not os.path.exists(t)
    u = writeback.undo(con, cid, now=NOW)
    (fr,) = u.blocked
    assert _kod(fr) == "undo_cut_kept" and dict(fr.reason.params)["paths"] == [k], fr.reason
    assert queries.kept_copy_frame_ids(con) == {_klatka(con)}
    con.close()


def _straz_pada_przy_zamknieciu(monkeypatch):
    """Zamknięcie transakcji podmiany pada po podmianie (C6) - kopia wyparta K zostaje obok ścieżki."""
    prawdziwa = repo.guard_file_replace

    class _Straz:
        def __init__(self, *a, **kw):
            self._s = prawdziwa(*a, **kw)

        def __enter__(self):
            return self._s.__enter__()

        def __exit__(self, *exc):
            self._s.__exit__(*exc)
            if exc[0] is None:
                raise RuntimeError("zamknięcie transakcji padło")
            return False
    monkeypatch.setattr(repo, "guard_file_replace", _Straz)


@pytest.mark.parametrize("awaria", ["kopia_nieusunieta", "zamkniecie_strazy"])
def test_wlasciciel_stawia_kept_i_obiecuje_porzadki_po_kanonicznym_werdykcie(tmp_path, monkeypatch,
                                                                            awaria):
    """Właściciel śladu na końcu własnego cofnięcia: kopia wyparta została (usunięcie odmówiło albo
    zamknięcie straży padło) - werdykt `kept` z trzema nazwami w tym samym wywołaniu, dopisek do wyniku
    obiecuje Porządki dopiero po kanonicznym `kept`, wiersz Porządków jest od razu, K bajtowo = plik
    zastany. Falsyfikator: werdykt właściciela zdjęty → bez dopisku i bez wiersza do następnego dotyku."""
    con, p, _zmiana, cid, n = _commit(tmp_path, "fits")
    if awaria == "kopia_nieusunieta":
        monkeypatch.setattr(writeback, "_usun_kopie", lambda kopia: PowodPozycji(
            f"kopia pliku sprzed podmiany została pod {kopia} (x) - zgodna z plikiem sprzed zapisu, "
            f"można ją skasować", "copy_not_removed", copy=kopia, detail="x"))
    else:
        _straz_pada_przy_zamknieciu(monkeypatch)
    u = writeback.undo(con, cid, now=NOW)
    monkeypatch.undo()
    (r,) = u.restored
    assert "undo_files_kept" in _kody(r), _kody(r)
    (s,) = _slady(con)
    k = _nazwy(s)[0]
    assert _werdykt(con, s["id"]) == ("kept", list(_nazwy(s)), NOW)
    assert _sha(k) == hashlib.sha1(n).hexdigest()
    assert queries.kept_copy_frame_ids(con) == {_klatka(con)}
    con.close()


@pytest.mark.parametrize("awaria", ["stan_nieznany", "zapis_werdyktu"])
def test_wlasciciel_bez_kanonicznego_kept_nie_obiecuje_porzadkow(tmp_path, monkeypatch, awaria):
    """Kopia wyparta została (C6), a werdykt nie zapadł - stan nazwy nieznany (`path_gone` → `None`)
    albo zapis werdyktu padł. Wynik NIE obiecuje Porządków (wiersza nie ma): dopisek mówi nazwy i receptę
    (`undo_files_unknown`) albo porażkę z klasą błędu (`undo_reconcile_failed`); ślad bez werdyktu, a
    następny dotyk (obserwator) widzi K → `kept`. Falsyfikator: obietnica Porządków bez kanonicznego
    `kept`."""
    con, p, _zmiana, cid, n = _commit(tmp_path, "fits")
    _straz_pada_przy_zamknieciu(monkeypatch)
    if awaria == "stan_nieznany":
        monkeypatch.setattr(scan, "path_gone", lambda x: None)
    else:
        def _pada(*a, **kw):
            raise sqlite3.OperationalError("database is locked")
        monkeypatch.setattr(repo, "settle_atomic_undo", _pada)
    u = writeback.undo(con, cid, now=NOW)
    monkeypatch.undo()
    (r,) = u.restored
    oczekiwany = "undo_files_unknown" if awaria == "stan_nieznany" else "undo_reconcile_failed"
    assert oczekiwany in _kody(r) and "undo_files_kept" not in _kody(r), _kody(r)
    (s,) = _slady(con)
    assert _werdykt(con, s["id"]) == (None, [], None)
    assert queries.kept_copy_frame_ids(con) == set()
    u2 = writeback.undo(con, cid, now=NOW)
    assert [_kod(f) for f in u2.blocked] == ["undo_cut_kept"], u2
    assert queries.kept_copy_frame_ids(con) == {_klatka(con)}
    con.close()


def test_zwykle_cofniecie_wlasciciel_zapisuje_clean(tmp_path, monkeypatch):
    """Zwykłe cofnięcie: właściciel sprzątnął K i zużył T - werdykt `clean` w tym samym wywołaniu; ponowienie
    nie ma czego rozstrzygać (zero wywołań klingi werdyktu). Falsyfikator: werdykt właściciela zdjęty → ślad
    bez werdyktu, bramka przy każdym dotyku."""
    con, p, _zmiana, cid, _n = _commit(tmp_path, "fits")
    assert writeback.undo(con, cid, now=NOW).complete
    (s,) = _slady(con)
    assert _werdykt(con, s["id"]) == ("clean", [], NOW)
    wolania = []
    prawdziwa = repo.settle_atomic_undo

    def _szpieg(*a, **kw):
        wolania.append(kw)
        return prawdziwa(*a, **kw)
    monkeypatch.setattr(repo, "settle_atomic_undo", _szpieg)
    u = writeback.undo(con, cid, now=NOW)
    assert [_kod(f) for f in u.already] == ["undo_already_own"] and wolania == [], (u, wolania)
    con.close()


def _martwy_po_podmianie(tmp_path, monkeypatch, rodzaj="fits"):
    """Ślad martwej próby: proces zginął po `ReplaceFileW`, przed rewalidacją - P = wynik, K = plik
    zastany, ślad bez werdyktu."""
    con, p, _zmiana, cid, n = _commit(tmp_path, rodzaj)

    def _smierc(*a, **kw):
        raise _Smierc()
    monkeypatch.setattr(writeback, "_rozjazd_odcisku", _smierc)
    with pytest.raises(_Smierc):
        writeback.undo(con, cid, now=NOW)
    monkeypatch.undo()
    (s,) = _slady(con)
    assert os.path.exists(_nazwy(s)[0]) and s["settled_at"] is None
    return con, p, cid, n, s


def test_obserwator_przy_stanie_nieznanym_przepuszcza_bez_werdyktu(tmp_path, monkeypatch):
    """Obserwator nie wie, czy pliki obok ścieżki są (`path_gone` → `None`) - nie pisze nic
    i nie blokuje (stan nieznany to nie brak, ale też nie dowód pliku); po odzyskaniu dostępu następny
    dotyk widzi K → `kept`. Falsyfikator: „nie wiem” jak „nie ma” → `clean`."""
    con, p, cid, n, s = _martwy_po_podmianie(tmp_path, monkeypatch)
    monkeypatch.setattr(scan, "path_gone", lambda x: None)
    u = writeback.undo(con, cid, now=NOW)
    monkeypatch.undo()
    assert "undo_cut_kept" not in [_kod(f) for f in u.blocked] and u.complete, u
    assert _werdykt(con, s["id"]) == (None, [], None)
    u2 = writeback.undo(con, cid, now=NOW)
    assert [_kod(f) for f in u2.blocked] == ["undo_cut_kept"], u2
    assert _werdykt(con, s["id"])[0] == "kept"
    con.close()


def test_przegrany_cas_obserwatora_bierze_werdykt_kanoniczny(tmp_path, monkeypatch):
    """Między odczytem dysku a zapisem `kept` obserwatora drugie połączenie zapisuje werdykt
    (właściciel `clean`). Przegrany CAS zwraca werdykt zwycięzcy - bramka przepuszcza, zdarzenia `kept`
    nie ma (emituje je wyłącznie zwycięski CAS). Falsyfikator: powód z własnego werdyktu mimo przegranej
    → blokada."""
    con, p, cid, n, s = _martwy_po_podmianie(tmp_path, monkeypatch)
    prawdziwa = repo.settle_atomic_undo

    def _wyprzedzony(con_, **kw):
        drugie = db.connect(str(tmp_path / "h.db"))
        prawdziwa(drugie, undo_id=kw["undo_id"], outcome="clean", kept_paths=(), now="2026-10-17")
        drugie.close()
        return prawdziwa(con_, **kw)
    monkeypatch.setattr(repo, "settle_atomic_undo", _wyprzedzony)
    assert writeback._rekoncyliuj_slady(con, _lokacja(con), now=NOW) is None
    monkeypatch.undo()
    assert _werdykt(con, s["id"]) == ("clean", [], "2026-10-17")
    assert con.execute("SELECT count(*) FROM event WHERE verb = 'location.displaced_kept'"
                       ).fetchone()[0] == 0
    con.close()


def test_commit_rozstrzyga_slady_cofniecia_lokacji(tmp_path, monkeypatch):
    """Bramka w zapisie karty: ślad martwej próby cofnięcia tej lokacji → `kept`, commit zablokowany raz
    (wpisy stagingu 'blocked'), plik nietknięty; po dokończeniu cofnięcia i ponownym stagingu commit idzie.
    Falsyfikator: bramka zdjęta z `_zapisz_lokacje` → werdyktu nie ma, Porządki puste."""
    con, p, cid, n, s = _martwy_po_podmianie(tmp_path, monkeypatch)
    loc = _lokacja(con)
    przed = _sha(p)
    _stage(con, "R2", loc["id"], "NGC 7000", loc["header_hash"])
    res = writeback.commit(con, "R2", now=NOW)
    (fr,) = res.blocked
    assert _kod(fr) == "undo_cut_kept" and _sha(p) == przed, res
    assert [r["status"] for r in writeback.pending_for_run(con, "R2")] == ["blocked"]
    assert _werdykt(con, s["id"])[0] == "kept" and queries.kept_copy_frame_ids(con) == {_klatka(con)}
    assert writeback.undo(con, cid, now=NOW).complete
    loc = _lokacja(con)
    _stage(con, "R3", loc["id"], "NGC 7000", loc["header_hash"])
    assert len(writeback.commit(con, "R3", now=NOW).applied) == 1
    con.close()


def test_klinga_werdyktu_cas_kanoniczny_zdarzenie_i_walidacja(tmp_path):
    """Klinga werdyktu: EXPECT przed bazą (elementy listy - niepuste teksty, lista niepusta ⟺ `kept`,
    werdykt ze zbioru) - zero zapisu; CAS raz, przegrany dostaje wiersz kanoniczny; zdarzenie
    `location.displaced_kept` wyłącznie po własnym CAS `kept`; ślady rozstrzygnięte znikają z zapytania
    bramki. Falsyfikator: walidacja elementów zdjęta → `[None]` wchodzi (CHECK go nie widzi)."""
    con, p, _zmiana, cid, _n = _commit(tmp_path, "fits")
    b = con.execute("SELECT id FROM header_backups").fetchone()[0]
    lid = con.execute("SELECT id FROM location").fetchone()[0]
    s = "a" * 40
    slady = [repo.record_atomic_undo(con, backup_id=b, result_sha1=s, result_size=1, result_hash=s,
                                     byte_exact=True, source_sha1=s, source_size=1,
                                     displaced_path=f"X:/L/k{i}", prepared_path=f"X:/L/t{i}", now=NOW)
             for i in (1, 2)]
    for outcome, sciezki in (("kept", [None]), ("kept", [1]), ("kept", [{}]), ("kept", [""]),
                             ("kept", []), ("clean", ["X:/L/k1"]), ("gone", [])):
        with pytest.raises(ValueError):
            repo.settle_atomic_undo(con, undo_id=slady[0], outcome=outcome, kept_paths=sciezki,
                                    now=NOW)
    assert _werdykt(con, slady[0]) == (None, [], None)
    nazwy = ["X:/L/k1", "X:/L/z1", "X:/L/t1"]
    w = repo.settle_atomic_undo(con, undo_id=slady[0], outcome="kept", kept_paths=nazwy, now=NOW)
    assert (w["outcome"], json.loads(w["kept_paths"]), w["settled_at"]) == ("kept", nazwy, NOW)
    w = repo.settle_atomic_undo(con, undo_id=slady[0], outcome="clean", kept_paths=(),
                                now="2026-10-17")
    assert (w["outcome"], w["settled_at"]) == ("kept", NOW)
    zdarzenia = [json.loads(r[0]) for r in con.execute(
        "SELECT payload FROM event WHERE verb = 'location.displaced_kept'")]
    assert zdarzenia == [{"undo_id": slady[0], "backup_id": b, "paths": nazwy}]
    assert [r["id"] for r in repo.unsettled_atomic_undos(con, lid)] == [slady[1]]
    con.close()


@pytest.mark.parametrize("polowa", ["zamiar_0038", "slad_0045"])
def test_porzadki_czytelnik_trojstanowy_i_totalny(tmp_path, monkeypatch, polowa):
    """Wiersz Porządków obu połów (zamiar podmiany 0038, ślad cofnięcia 0045) - nazwa znika
    WYŁĄCZNIE po dowiedzionym braku (ostatni odczyt przeglądu tła w pamięci obecności → `True`), „nie wiem”
    i nazwa jeszcze niesprawdzona zostają widoczne; elementy spoza niepustych tekstów (CHECK ich nie widzi)
    są pomijane bez wywrócenia Porządków. Czytelnik NIE dotyka dysku (AR-246) - `scan.path_gone` niewołane.
    Falsyfikatory: `None` jak brak → wiersz znika przy zerwanym udziale; czytelnik bez filtra →
    `TypeError`; czytelnik statujący dysk."""
    con, p, _zmiana, cid, _n = _commit(tmp_path, "fits")
    b = con.execute("SELECT id FROM header_backups").fetchone()[0]
    jest = tmp_path / "a.fits.0000abcd.horreum-kopia"
    jest.write_bytes(b"k")
    brak = str(tmp_path / "a.fits.0000abce.horreum-kopia")
    niepewna = str(tmp_path / "a.fits.0000abcf.horreum-kopia")
    queries.zapomnij_obecnosc()
    for nazwa, odczyt in ((str(jest), scan.path_gone(str(jest))), (brak, scan.path_gone(brak)),
                          (niepewna, None)):
        queries.zapamietaj_obecnosc(nazwa, queries.bilet_obecnosci(), odczyt)
    assert queries.obecnosc_kopii([str(jest), brak, niepewna, "X:/L/nigdy"]) == {
        str(jest): False, brak: True, niepewna: None}

    def _stat(x):
        raise AssertionError(f"czytelnik Porządków statuje dysk: {x}")
    monkeypatch.setattr(scan, "path_gone", _stat)
    if polowa == "slad_0045":
        s = "a" * 40
        u = repo.record_atomic_undo(con, backup_id=b, result_sha1=s, result_size=1, result_hash=s,
                                    byte_exact=True, source_sha1=s, source_size=1,
                                    displaced_path="X:/L/k", prepared_path="X:/L/t", now=NOW)

        def _wpisz(sciezki):
            con.execute("UPDATE atomic_undo SET outcome = 'kept', kept_paths = ?, settled_at = ? "
                        "WHERE id = ?", (sciezki, NOW, u))
            con.commit()
    else:
        def _wpisz(sciezki):
            con.execute("UPDATE replace_intent SET outcome = 'kept', kept_paths = ? WHERE backup_id = ?",
                        (sciezki, b))
            con.commit()
    fid = _klatka(con)
    nigdy = str(tmp_path / "a.fits.0000abd0.horreum-kopia")         # niesprawdzona w tym procesie
    for sciezki, widoczny in (('[null, 1, {}, ""]', False), (json.dumps([brak]), False),
                              (json.dumps([niepewna]), True), (json.dumps([None, str(jest)]), True),
                              (json.dumps([brak, nigdy]), True)):
        _wpisz(sciezki)
        assert (queries.kept_copy_frame_ids(con) == {fid}) is widoczny, sciezki
    queries.zapomnij_obecnosc()
    con.close()


@pytest.mark.parametrize("skad", ["kopia_bajtowa", "obcy_odklada_wynik"])
def test_duplikat_pliku_pod_sciezka_zostaje_do_oka(tmp_path, monkeypatch, skad):
    """Automat nie kasuje NICZEGO, także bajtowej kopii pliku pod ścieżką - kopia wyparta równa P
    (wyidealizowane S = R) albo obcy pisarz w oknie podmiany odłożył dokładnie wynik (P = R i K = R po
    śmierci przed powrotem). Bramka: `kept`, K bajtowo nietknięta. Falsyfikator: kasowanie duplikatu."""
    if skad == "kopia_bajtowa":
        con, p, _zmiana, cid, _n = _commit(tmp_path, "fits")
        b = con.execute("SELECT id FROM header_backups").fetchone()[0]
        k = str(p) + ".0000abcd" + writeback._KOPIA_SUFFIX
        shutil.copyfile(p, k)
        s = "a" * 40
        repo.record_atomic_undo(con, backup_id=b, result_sha1=s, result_size=1, result_hash=s,
                                byte_exact=True, source_sha1=s, source_size=1, displaced_path=k,
                                prepared_path=str(tmp_path / "brak.tmp"), now=NOW)
    else:
        con, p, _zmiana, cid, _n = _commit(tmp_path, "fits")
        prawdziwa, wolania = writeback._replace_file_w, []

        def _replace(dst, src, kopia):
            wolania.append(1)
            if len(wolania) == 1:                       # obcy zapis: dokładnie wynik cofnięcia
                st = os.stat(dst)
                shutil.copyfile(src, dst)
                os.utime(dst, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))
            prawdziwa(dst, src, kopia)

        def _smierc(*a, **kw):
            raise _Smierc()
        monkeypatch.setattr(writeback, "_replace_file_w", _replace)
        monkeypatch.setattr(writeback, "_oddaj_wyparty", _smierc)
        with pytest.raises(_Smierc):
            writeback.undo(con, cid, now=NOW)
        monkeypatch.undo()
        (s_,) = _slady(con)
        k = _nazwy(s_)[0]
    assert _sha(k) == _sha(p)
    przed = _sha(k)
    u = writeback.undo(con, cid, now=NOW)
    assert "undo_cut_kept" in [_kod(f) for f in u.blocked], u
    assert os.path.exists(k) and _sha(k) == przed
    con.close()


def test_nowe_zdania_plikow_obok_sciezki_PL_i_EN(tmp_path, monkeypatch):
    """Zdania z prawdziwych dróg (bramka `kept`, dopisek właściciela `kept`, stan nieznany, porażka
    zapisu werdyktu) w obu językach okna: PL == proza rdzenia (`czytelny_powod`), EN bez polskich liter
    i bez niewypełnionych pól; proza z kontrolowanymi ścieżkami mieści się w cp1250 (druk CLI)."""
    pytest.importorskip("PySide6")
    from horreum.gui import i18n
    from horreum.gui.wb_worker import czytelny_powod, tekst_powodu
    con, p, _zmiana, cid, _n = _commit(tmp_path, "fits")
    b = con.execute("SELECT id FROM header_backups").fetchone()[0]
    s = "a" * 40
    u = repo.record_atomic_undo(con, backup_id=b, result_sha1=s, result_size=1, result_hash=s,
                                byte_exact=True, source_sha1=s, source_size=1,
                                displaced_path="X:\\L\\a.fits.0000abcd.horreum-kopia",
                                prepared_path="X:\\L\\tmp1.tmp", now=NOW)
    nazwy = writeback._nazwy_sladu("X:\\L\\a.fits.0000abcd.horreum-kopia", "X:\\L\\tmp1.tmp")
    monkeypatch.setattr(scan, "path_gone", lambda x: x != nazwy[0])
    wlasciciel = dict(commit_id=cid, now=NOW, resync_potwierdzony=True)
    powody = [writeback._rekoncyliuj_slady(con, _lokacja(con), now=NOW),
              writeback._werdykt_wlasciciela(con, u, nazwy, **wlasciciel)]
    monkeypatch.setattr(scan, "path_gone", lambda x: None)
    powody.append(writeback._werdykt_wlasciciela(con, u, nazwy, **wlasciciel))

    def _pada(*a, **kw):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(scan, "path_gone", lambda x: False)
    monkeypatch.setattr(repo, "settle_atomic_undo", _pada)
    powody.append(writeback._werdykt_wlasciciela(con, u, nazwy, **wlasciciel))
    assert [x.code for x in powody] == ["undo_cut_kept", "undo_files_kept", "undo_files_unknown",
                                        "undo_reconcile_failed"], powody
    for powod in powody:
        str(powod).encode("cp1250")
        for lang in ("pl", "en"):
            i18n.set_lang(lang)
            zdanie = tekst_powodu(powod)
            assert "{" not in zdanie, zdanie
            if lang == "pl":
                assert zdanie == czytelny_powod(str(powod)), (zdanie, str(powod))
            else:
                assert not set(zdanie) & set("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ„”"), zdanie
    i18n.set_lang("pl")
    con.close()


def test_przegrany_cas_wlasciciela_rozstrzyga_wiersz_kanoniczny(tmp_path, monkeypatch):
    """Właściciel proponuje `clean` (jego inwentaryzacja: nic obok ścieżki), a obserwator między tą
    inwentaryzacją a zapisem wygrywa `kept`, bo widział plik (tu: kopia pojawia się pod nazwą K).
    Rozstrzyga wiersz kanoniczny: `kept` - dopisek Porządków z nazwą, której brak nie jest
    dowiedziony, i wiersz Porządków. Falsyfikator: właściciel ignoruje przegrany CAS → bez dopisku."""
    con, p, _zmiana, cid, _n = _commit(tmp_path, "fits")
    prawdziwa = repo.settle_atomic_undo
    widziane = []

    def _wyprzedzony(con_, **kw):
        if kw["outcome"] == "clean":
            s = con_.execute("SELECT displaced_path, prepared_path FROM atomic_undo WHERE id = ?",
                             (kw["undo_id"],)).fetchone()
            nazwy = writeback._nazwy_sladu(s[0], s[1])
            with open(nazwy[0], "wb") as fh:
                fh.write(b"k")
            widziane.append(nazwy)
            drugie = db.connect(str(tmp_path / "h.db"))
            prawdziwa(drugie, undo_id=kw["undo_id"], outcome="kept", kept_paths=nazwy,
                      now="2026-10-17")
            drugie.close()
        return prawdziwa(con_, **kw)
    monkeypatch.setattr(repo, "settle_atomic_undo", _wyprzedzony)
    u = writeback.undo(con, cid, now=NOW)
    monkeypatch.undo()
    (r,) = u.restored
    (nazwy,) = widziane
    noty = {getattr(n, "code", None): n for n in dict(r.reason.params).get("notes", ())}
    assert _kod(r) == "undo_files_kept" or "undo_files_kept" in noty, _kody(r)
    dopisek = r.reason if _kod(r) == "undo_files_kept" else noty["undo_files_kept"]
    assert dict(dopisek.params)["paths"] == [nazwy[0]], dopisek
    (s,) = _slady(con)
    assert _werdykt(con, s["id"]) == ("kept", list(nazwy), "2026-10-17")
    assert queries.kept_copy_frame_ids(con) == {_klatka(con)}
    con.close()


@pytest.mark.parametrize("wynik", ["resync_padl", "inny_pisarz_wrocil"])
def test_clean_tylko_po_potwierdzonym_resyncu(tmp_path, monkeypatch, wynik):
    """Obok ścieżki nic nie zostało, ale re-sync tej próby nie zapadł - padł ('failed') albo wersja
    innego pisarza wróciła pod ścieżkę ('blocked'): właściciel nie pisze `clean`, ślad zostaje bez
    werdyktu (bramka spróbuje przy następnym dotyku). Falsyfikator: `clean` bez potwierdzonego
    re-syncu."""
    con, p, zmiana, cid, _n = _commit(tmp_path, "fits2hdu")
    if wynik == "resync_padl":
        monkeypatch.setattr(writeback.scan, "scan_file",
                            lambda path, **kw: (_ for _ in ()).throw(OSError(64, "zerwany udział")))
    else:
        prawdziwa, wolania = writeback._replace_file_w, []

        def _replace(dst, src, kopia):
            wolania.append(1)
            if len(wolania) == 1:
                zmiana(p)                              # cudzy zapis tuż przed podmianą
            prawdziwa(dst, src, kopia)
        monkeypatch.setattr(writeback, "_replace_file_w", _replace)
    u = writeback.undo(con, cid, now=NOW)
    monkeypatch.undo()
    assert not u.restored and not u.complete, u
    (s,) = _slady(con)
    assert all(not os.path.exists(x) for x in _nazwy(s))
    assert _werdykt(con, s["id"]) == (None, [], None)
    con.close()


# ============================================================ AR-231: przegląd śladów bez werdyktu


def _slady_trzech_lokacji(tmp_path):
    """Baza z trzema plikami po jednym commicie drogą atomową i ślad cofnięcia (bez werdyktu) przy każdym
    backupie - nazwy K, Z, T śladu w katalogu pliku, żadna jeszcze na dysku. `(con, pliki, slady)`."""
    con = db.open_db(str(tmp_path / "h.db"))
    pliki = []
    for i in range(3):
        (tmp_path / f"L{i}").mkdir()
        pliki.append(_fits(tmp_path / f"L{i}" / "a.fits", seed=i))
    for p in pliki:
        _scan_in(con, p)
    for lid, hh in con.execute("SELECT id, header_hash FROM location ORDER BY id").fetchall():
        _stage(con, "R", lid, "NGC 7000", hh)
    res = writeback.commit(con, "R", now=NOW)
    assert len(res.applied) == 3, res
    s = "a" * 40
    slady = []
    for b, p in zip(con.execute("SELECT id FROM header_backups ORDER BY location_id").fetchall(),
                    pliki):
        slady.append(repo.record_atomic_undo(
            con, backup_id=b[0], result_sha1=s, result_size=1, result_hash=s, byte_exact=True,
            source_sha1=s, source_size=1, displaced_path=str(p) + ".0000abcd.horreum-kopia",
            prepared_path=str(p.parent / "tmp1.tmp"), now=NOW))
    return con, pliki, slady


def _odcisk_plikow(sciezki):
    return {str(x): (_sha(x), os.stat(x).st_mtime_ns) if os.path.exists(x) else None for x in sciezki}


def test_przeglad_sladow_wszystkie_lokacje_tylko_kept(tmp_path, monkeypatch):
    """AR-231: przegląd śladów bez werdyktu WSZYSTKICH lokacji tym samym obserwatorem co bramka - plik
    tymczasowy martwej próby jest na dysku → `kept` z trzema nazwami, zdarzenie i wiersz Porządków bez
    dotyku lokacji; obok ścieżki nic → ślad BEZ werdyktu (`clean` pisze wyłącznie właściciel); „nie wiem”
    → bez werdyktu, ale osobno (`nie_wiem` - stan dysku nieznany, Porządki mówią o nim zdaniem). Pliki
    P/K/Z/T nietknięte (sha1 i `mtime`).
    Falsyfikatory: przegląd zapisuje `clean` po trzech „nie ma”; przegląd jednej lokacji; „nie wiem” liczone
    jak trzy braki."""
    con, pliki, slady = _slady_trzech_lokacji(tmp_path)
    nazwy = [_nazwy(s) for s in _slady(con)]
    with open(nazwy[0][2], "wb") as fh:                            # T martwej próby lokacji 0
        fh.write(b"T" * 64)
    niepewna = nazwy[2][0]                                         # K lokacji 2: „nie wiem”
    prawdziwa = scan.path_gone
    monkeypatch.setattr(scan, "path_gone", lambda x: None if x == niepewna else prawdziwa(x))
    wszystkie = [*map(str, pliki), *(x for n in nazwy for x in n)]
    przed = _odcisk_plikow(wszystkie)
    wynik = writeback.przejrzyj_slady_cofniecia(con, now=NOW)
    monkeypatch.undo()
    assert wynik == writeback.PrzegladSladow(kept=(slady[0],), bez_werdyktu=(slady[1],),
                                             nie_wiem=(slady[2],), nie_wiem_nazwy=(niepewna,)), wynik
    assert _werdykt(con, slady[0]) == ("kept", list(nazwy[0]), NOW)
    assert _werdykt(con, slady[1]) == (None, [], None) and _werdykt(con, slady[2]) == (None, [], None)
    assert con.execute("SELECT count(*) FROM event WHERE verb = 'location.displaced_kept'"
                       ).fetchone()[0] == 1
    fid0 = con.execute("SELECT frame_id FROM location WHERE path = ?", (str(pliki[0]),)).fetchone()[0]
    assert queries.kept_copy_frame_ids(con) == {fid0}
    assert _odcisk_plikow(wszystkie) == przed
    con.close()


def test_przeglad_liczy_z_wiersza_kanonicznego(tmp_path, monkeypatch):
    """AR-231: między odczytem dysku a CAS przeglądu właściciel (drugie połączenie) zapisuje `clean` -
    przegląd liczy werdykt z WIERSZA KANONICZNEGO (`clean`), nie z własnej propozycji; zdarzenia `kept`
    nie ma. Falsyfikator: licznik z propozycji → ślad w `kept`."""
    con, pliki, slady = _slady_trzech_lokacji(tmp_path)
    with open(_nazwy(_slady(con)[0])[0], "wb") as fh:
        fh.write(b"K" * 64)
    prawdziwa = repo.settle_atomic_undo

    def _wyprzedzony(con_, **kw):
        if kw["undo_id"] == slady[0]:
            drugie = db.connect(str(tmp_path / "h.db"))
            prawdziwa(drugie, undo_id=kw["undo_id"], outcome="clean", kept_paths=(), now="2026-10-17")
            drugie.close()
        return prawdziwa(con_, **kw)
    monkeypatch.setattr(repo, "settle_atomic_undo", _wyprzedzony)
    wynik = writeback.przejrzyj_slady_cofniecia(con, now=NOW)
    monkeypatch.undo()
    assert wynik.clean == (slady[0],) and wynik.kept == (), wynik
    assert con.execute("SELECT count(*) FROM event WHERE verb = 'location.displaced_kept'"
                       ).fetchone()[0] == 0
    con.close()


def _prawdziwy_blad_zajetej_bazy(tmp_path):
    """PRAWDZIWY `SQLITE_BUSY` (z `sqlite_errorcode`) - druga baza w `BEGIN EXCLUSIVE`, odczyt bez czekania.
    Sztuczny `OperationalError("database is locked")` kodu nie niesie i klasy `db_busy` nie dostaje."""
    p = str(tmp_path / "zajeta.db")
    a = sqlite3.connect(p)
    a.execute("CREATE TABLE t (x)")
    a.commit()
    a.execute("BEGIN EXCLUSIVE")
    b = sqlite3.connect(p, timeout=0)
    try:
        b.execute("SELECT * FROM t").fetchall()
    except sqlite3.OperationalError as exc:
        return exc
    finally:
        b.close()
        a.rollback()
        a.close()
    raise AssertionError("odczyt przy BEGIN EXCLUSIVE przeszedł - brak SQLITE_BUSY")


def test_przeglad_awaria_jednego_sladu_nie_przerywa(tmp_path, monkeypatch):
    """AR-231: zapis werdyktu jednego śladu pada (baza zablokowana) - ślad w `padly` z powodem klasy
    (`undo_reconcile_failed`, szczegół `db_busy`), pozostałe rozstrzygnięte w tym samym przeglądzie.
    Falsyfikator: przerwanie przeglądu przy pierwszej porażce."""
    con, pliki, slady = _slady_trzech_lokacji(tmp_path)
    for s in _slady(con):
        with open(_nazwy(s)[0], "wb") as fh:
            fh.write(b"K" * 64)
    prawdziwa = repo.settle_atomic_undo
    zajeta = _prawdziwy_blad_zajetej_bazy(tmp_path)

    def _pada(con_, **kw):
        if kw["undo_id"] == slady[0]:
            raise zajeta
        return prawdziwa(con_, **kw)
    monkeypatch.setattr(repo, "settle_atomic_undo", _pada)
    wynik = writeback.przejrzyj_slady_cofniecia(con, now=NOW)
    monkeypatch.undo()
    assert wynik.padly == (slady[0],) and wynik.kept == (slady[1], slady[2]), wynik
    assert wynik.powod.code == "undo_reconcile_failed", wynik.powod
    assert dict(wynik.powod.params)["detail"].code == "db_busy"
    assert _werdykt(con, slady[0]) == (None, [], None)
    con.close()
