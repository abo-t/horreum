"""Testy DOPISANIA KARTY FITS W MIEJSCU (AR-118, zamyka AR-117) - `writeback.write_changes_inplace`
z operacją `add` karty tekstowej, której w nagłówku nie ma.

Karta idzie w ZAPAS nagłówka (pusta karta na końcu albo wolny rekord za `END` w ostatnim bloku
2880 B), a kolejność kart wyznacza astropy - `_apply_op`, ta sama funkcja, która łata drogę atomową;
bez zapasu `Fallback` (droga atomowa przepisuje plik). KOTWICA POPRAWNOŚCI: karty po łacie w miejscu
== karty drogi atomowej (`write_changes`) dla tych samych operacji, KOLEJNOŚĆ włącznie, i ten sam
`header_hash`. Wobec PLIKU drogi atomowej: bajt w bajt dla plików bez skali pseudo-unsigned, a dla
układu NINA (`BZERO` bez `BSCALE`) z pominięciem `BSCALE`/`BZERO`, które `writeto` kanonizuje
(`test_add_uklad_NINA_karty_jak_atom_poza_skala`).

Pliki FITS SYNTETYCZNE w `tmp_path`; nagłówki, których astropy sam nie napisze (pusta karta
w środku, zera za `END`, karta niestandardowa, układ NINA), składane z bajtów. Helpery pisarza
i orkiestracji - z `test_writeback_inplace`."""

from __future__ import annotations

import hashlib
import os
import re
import shutil

import numpy as np
import pytest
from astropy.io import fits

from horreum import cli, db, repo, scan, writeback
from test_header_fix import _archiwum, _cli, _karty, _plan
from test_writeback_inplace import (NOW, _Dziennik, _NieWolno, _Przerwa, _hash, _loc, _operacje,
                                    _psuj_fsync, _scan_in, _zerwany_udzial)

SKALA = ("BSCALE", "BZERO")
OBOWIAZKOWE = ("SIMPLE  =                    T", "BITPIX  =                   16",
               "NAXIS   =                    2", "NAXIS1  =                    4",
               "NAXIS2  =                    4")


def _fits_bez(path, *, karty=(("IMAGETYP", "Light"),), puste=0, zapas=None, seed=0):
    """FITS bez karty `OBJECT` zapisany przez astropy. `karty` = `(kw, wartość[, komentarz])` albo
    `("HISTORY"|"COMMENT", tekst)`; `puste` = puste karty przed `END`; `zapas` = dokładna liczba
    wolnych rekordów za `END` w ostatnim bloku (dopełnienie kartami `PADn`; `0` = `END` na ostatnim
    rekordzie bloku), `None` = bez dopełnienia."""
    hdu = fits.PrimaryHDU(data=np.arange(64, dtype=np.int16).reshape(8, 8) + seed)
    for k in karty:
        if k[0] == "HISTORY":
            hdu.header.add_history(k[1])
        elif k[0] == "COMMENT":
            hdu.header.add_comment(k[1])
        else:
            hdu.header.append(k)
    i = 0
    while zapas is not None and (len(hdu.header) + puste + 1 + zapas) % 36:
        hdu.header.append((f"PAD{i}", i))
        i += 1
    for _ in range(puste):
        hdu.header.append(fits.Card(), end=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    hdu.writeto(path, overwrite=True)
    return path


def _fits_z_bajtow(path, linie, *, wypelnienie=b" "):
    """FITS (int16 4x4) składany z bajtów: karty obowiązkowe, `linie`, `END`, wypełnienie bloku
    `wypelnienie`, dane."""
    raw = b"".join(x.encode("ascii").ljust(80) for x in (*OBOWIAZKOWE, *linie))
    raw += writeback._FITS_END_RECORD
    raw += wypelnienie * (-len(raw) % 2880)
    dane = np.arange(16, dtype=">i2").tobytes()
    path.write_bytes(raw + dane + b"\x00" * (2880 - len(dane)))
    return path


def _add(kw="OBJECT", value="NGC 7635", comment=None):
    return writeback.WriteOp(kw, "add", value, "str", comment=comment)


def _set(kw, value, comment=None):
    return writeback.WriteOp(kw, "set", value, "str", idx=0, comment=comment)


def _sha1(path):
    return hashlib.sha1(path.read_bytes()).hexdigest()


def _dwie_drogi(p, ops):
    """Te same operacje na dwóch kopiach `p`: droga atomowa (`write_changes`) i zapis w miejscu.
    → `(wynik atomu, wynik w miejscu, kopia atomu, kopia w miejscu, st_ino kopii w miejscu)`."""
    atom = p.with_name(p.stem + "_atom.fits")
    wm = p.with_name(p.stem + "_wm.fits")
    shutil.copyfile(p, atom)
    shutil.copyfile(p, wm)
    ino = os.stat(wm).st_ino
    ra = writeback.write_changes(str(atom), ops, _hash(atom))
    rw = writeback.write_changes_inplace(str(wm), ops, _hash(wm), journal=_Dziennik())
    return ra, rw, atom, wm, ino


def _stage_add(con, run_id, lid, expected, keyword="OBJECT", value="NGC 7635"):
    repo.stage_pending(con, run_id=run_id, location_id=lid, keyword=keyword, idx=None, op="add",
                       old_value=None, new_value=value, new_type="str", new_comment=None,
                       expected_header_hash=expected)


def _baza_z_add(tmp_path, plik):
    con = db.open_db(str(tmp_path / "h.db"))
    _scan_in(con, plik)
    loc = _loc(con, plik)
    _stage_add(con, "R", loc["id"], loc["header_hash"])
    return con, loc


# ============================================================ PISARZ: równoważność z drogą atomową


@pytest.mark.parametrize("plik, ops, bajty_jak_atom", [
    pytest.param(lambda tp: _fits_bez(tp / "a.fits", karty=[("IMAGETYP", "Light"),
                                                           ("TELESCOP", "RC8")]),
                 [_add()], True, id="bez_pustych_kart"),
    pytest.param(lambda tp: _fits_bez(tp / "a.fits", karty=[("IMAGETYP", "Light"),
                                                           ("TELESCOP", "RC8")], puste=3),
                 [_add()], True, id="puste_karty_przed_END"),
    pytest.param(lambda tp: _fits_bez(tp / "a.fits", karty=[("IMAGETYP", "Light"), ("HISTORY", "h1"),
                                                           ("HISTORY", "h2")]),
                 [_add()], True, id="HISTORY_na_koncu"),
    pytest.param(lambda tp: _fits_bez(tp / "a.fits", karty=[("IMAGETYP", "Light"), ("COMMENT", "c1"),
                                                           ("HISTORY", "h1")], puste=2),
                 [_add()], True, id="COMMENT_HISTORY_i_puste"),
    pytest.param(lambda tp: _fits_bez(tp / "a.fits", puste=1, zapas=0),
                 [_add()], True, id="END_na_ostatnim_rekordzie_z_pusta_karta"),
    pytest.param(lambda tp: _fits_bez(tp / "a.fits", puste=1),
                 [_add(), _add("OBSERVER", "Zdzin")], True, id="dwa_add_jedna_pusta"),
    pytest.param(lambda tp: _fits_bez(tp / "a.fits", karty=[("IMAGETYP", "Light"),
                                                           ("TELESCOP", "RC8")]),
                 [_set("TELESCOP", "RC6"), _add()], True, id="set_i_add"),
    pytest.param(lambda tp: _fits_bez(tp / "a.fits"),
                 [_add(comment="Name of the object")], True, id="add_z_komentarzem"),
    pytest.param(lambda tp: _fits_bez(tp / "a.fits", karty=[("IMAGETYP", "Light"),
                                                           ("NOTES", "Y" * 90)]),
                 [_add()], True, id="karta_CONTINUE_w_naglowku"),
    pytest.param(lambda tp: _fits_z_bajtow(tp / "a.fits", ["IMAGETYP= 'Light   '", "",
                                                           "HISTORY h1"]),
                 [_add()], True, id="pusta_karta_w_srodku_przed_HISTORY"),
    pytest.param(lambda tp: _fits_z_bajtow(tp / "a.fits", ["IMAGETYP= 'Light   '",
                                                           "        tekst"]),
                 [_add()], True, id="komentarz_bez_slowa_na_koncu"),
    pytest.param(lambda tp: _fits_z_bajtow(tp / "a.fits", ["IMAGETYP= 'Light   '",
                                                           "lowkw   =                    1"]),
                 [_add()], False, id="cudza_karta_niestandardowa"),
])
def test_add_rownowazny_drodze_atomowej(tmp_path, plik, ops, bajty_jak_atom):
    """Kotwica AR-118: karty po łacie w miejscu == karty drogi atomowej dla tych samych operacji
    (KOLEJNOŚĆ włącznie - astropy stawia dopisaną kartę przed końcowym blokiem COMMENT/HISTORY/
    pustych i zużywa pustą kartę z końca), ten sam `header_hash`, rozmiar, `st_ino` i dane bez
    zmian. Plik bajt w bajt == atom, gdy astropy nie przekłada cudzych kart; karta niestandardowa
    zostaje w miejscu nietknięta (atom ją „naprawia”), więc tam równe są karty i hash, nie bajty.

    Falsyfikatory: karta zawsze w miejscu `END` → padają przypadki z HISTORY/pustymi; bez zużycia
    pustej karty → padają przypadki z pustymi; `want` sprzed AR-118 → weryfikacja rzuca."""
    p = plik(tmp_path)
    przed = p.read_bytes()
    ra, rw, atom, wm, ino = _dwie_drogi(p, ops)
    assert ra.status == "applied", ra
    assert isinstance(rw, writeback.WriteResult) and rw.status == "applied" and rw.in_place, rw
    assert os.path.getsize(wm) == len(przed) and os.stat(wm).st_ino == ino
    ma, mw = scan.read_fits_meta(str(atom)), scan.read_fits_meta(str(wm))
    assert mw.cards == ma.cards and mw.header_hash == ma.header_hash == rw.post_hash
    assert mw.datloc == scan.read_fits_meta(str(p)).datloc
    assert wm.read_bytes()[mw.datloc:] == przed[mw.datloc:]                 # dane bajt w bajt
    assert (wm.read_bytes() == atom.read_bytes()) is bajty_jak_atom


@pytest.mark.parametrize("plik, ops, fragment", [
    pytest.param(lambda tp: _fits_bez(tp / "b.fits", zapas=0), [_add()],
                 "potrzebuje 1 wolnego rekordu", id="END_na_ostatnim_rekordzie_bloku"),
    pytest.param(lambda tp: _fits_z_bajtow(tp / "b.fits", ["IMAGETYP= 'Light   '"],
                                           wypelnienie=b"\x00"),
                 [_add()], "potrzebuje 1 wolnego rekordu", id="zera_za_END"),
    pytest.param(lambda tp: _fits_bez(tp / "b.fits", zapas=1),
                 [_add(), _add("OBSERVER", "Zdzin")], "potrzebuje 2", id="dwa_add_jeden_wolny_rekord"),
    pytest.param(lambda tp: _fits_bez(tp / "b.fits", zapas=0),
                 [writeback.WriteOp("FOCALLEN", "add", "800", "int")],
                 "potrzebuje 1 wolnego rekordu", id="add_liczby_bez_zapasu"),
])
def test_add_bez_miejsca_spada_przed_zapisem(tmp_path, plik, ops, fragment):
    """Brak zapasu (nagłówek urósłby o blok i przesunął dane) - także przy karcie liczbowej, która
    od AR-261 idzie w miejscu, gdy zapas jest → `Fallback` PRZED dziennikiem i zapisem, plik bajt
    w bajt nietknięty. `add` karty obecnej to odmowa, nie spadek (AR-257, blok na końcu pliku)."""
    p = plik(tmp_path)
    przed = p.read_bytes()
    res = writeback.write_changes_inplace(str(p), ops, _hash(p), journal=_NieWolno())
    assert isinstance(res, writeback.Fallback) and fragment in res.reason, res
    assert p.read_bytes() == przed


def test_add_uklad_NINA_karty_jak_atom_poza_skala(tmp_path):
    """Układ NINA (`BZERO = 32768` zaraz po `NAXIS2`, bez `BSCALE`) - 83 z 83 lightów bez `OBJECT`
    na `R:` (sonda 2026-10-15). Droga atomowa przy `writeto` kanonizuje skalę danych
    pseudo-unsigned: dopisuje `BSCALE = 1` i przenosi `BZERO` na koniec. Zapis w miejscu kart układu
    nie rusza (bramka `_fits_layout`), więc z drogą atomową zgadza się WYŁĄCZNIE poza `BSCALE`/
    `BZERO`; dane bez zmian w obu drogach."""
    p = _fits_z_bajtow(tmp_path / "nina.fits", ["BZERO   =                32768 /",
                                                 "EXTEND  =                    T",
                                                 "IMAGETYP= 'LIGHT   '"])
    ra, rw, atom, wm, ino = _dwie_drogi(p, [_add()])
    assert ra.status == "applied" and rw.status == "applied" and rw.in_place
    ma, mw = scan.read_fits_meta(str(atom)), scan.read_fits_meta(str(wm))
    bez_skali = lambda karty: [c for c in karty if c.keyword not in SKALA]
    assert bez_skali(mw.cards) == bez_skali(ma.cards)
    assert [c.keyword for c in ma.cards][-2:] == ["BSCALE", "BZERO"]          # kanonizacja atomu
    assert [c.keyword for c in mw.cards] == ["SIMPLE", "BITPIX", "NAXIS", "NAXIS1", "NAXIS2",
                                             "BZERO", "EXTEND", "IMAGETYP", "OBJECT"]
    sha_danych = scan.scan_file(str(p)).sha1_data
    assert scan.scan_file(str(atom)).sha1_data == scan.scan_file(str(wm)).sha1_data == sha_danych


def test_set_w_miejscu_niesie_komentarz_operacji_jak_droga_atomowa(tmp_path):
    """`set` z komentarzem: zapis w miejscu brał ZASTANY komentarz i po cichu gubił zmianę
    (`applied` + stary komentarz), a droga atomowa (`_apply_op`) wpisuje komentarz operacji.
    Teraz obie drogi dają tę samą kartę. Falsyfikator: obraz karty z `card.comment` → weryfikacja
    przed zapisem rzuca (karty rozjechane z `_apply_op`)."""
    p = _fits_bez(tmp_path / "k.fits", karty=[("IMAGETYP", "Light"),
                                              ("OBJECT", "M31", "stary komentarz")])
    ra, rw, atom, wm, ino = _dwie_drogi(p, [_set("OBJECT", "M 31", "nowy komentarz")])
    assert ra.status == "applied" and rw.status == "applied" and rw.in_place, rw
    assert fits.getheader(str(wm)).comments["OBJECT"] == "nowy komentarz"
    assert scan.read_fits_meta(str(wm)).cards == scan.read_fits_meta(str(atom)).cards


def test_add_z_komentarzem_daje_SZTYWNY_rekord_80_B_i_END_rekord_nizej(tmp_path):
    """Kotwica niezależna od `_apply_op` i `_fits_card_image` (obie drogi z `_dwie_drogi` je
    dzielą, więc wspólny błąd układu karty przeszedłby niezauważony): rekord dopisanej karty jest
    literałem bajtów - pole wartości stałego formatu (apostrof w kolumnie 11, pole do kolumny 30),
    ` / ` i komentarz z operacji - a `END` stoi rekord niżej, za nim 80 spacji. Reszta pliku
    bajt w bajt."""
    p = _fits_bez(tmp_path / "r.fits")
    przed = p.read_bytes()
    end = b"END" + b" " * 77
    karta = b"OBJECT  = 'NGC 7635'           / Name of the object".ljust(80)
    assert len(karta) == 80 and przed[7 * 80:8 * 80] == end          # 7 kart, END na rekordzie 7
    res = writeback.write_changes_inplace(str(p), [_add(comment="Name of the object")], _hash(p))
    assert res.status == "applied" and res.in_place, res
    po = p.read_bytes()
    assert po[7 * 80:8 * 80] == karta
    assert po[8 * 80:9 * 80] == end and po[9 * 80:10 * 80] == b" " * 80
    assert po[:7 * 80] == przed[:7 * 80] and po[10 * 80:] == przed[10 * 80:]


def test_add_pisarz_dziennik_i_zakres_zapisu(tmp_path):
    """Dopisanie przed `END`: region tej samej długości, zakres zapisu = rekord nowej karty i stary
    `END` (zjeżdża o 80 B w wolny rekord), backup = surowy region sprzed zapisu, faza `written`,
    `st_ino`, rozmiar i dane bez zmian."""
    p = _fits_bez(tmp_path / "z.fits")
    przed = p.read_bytes()
    ino = os.stat(p).st_ino
    dz = _Dziennik()
    res = writeback.write_changes_inplace(str(p), [_add()], _hash(p), journal=dz)
    assert res.status == "applied" and res.in_place, res
    po = p.read_bytes()
    assert len(po) == len(przed) and os.stat(p).st_ino == ino and po[2880:] == przed[2880:]
    koniec = przed[:2880].index(writeback._FITS_END_RECORD)
    assert koniec % 80 == 0 and po[koniec + 80:koniec + 160] == writeback._FITS_END_RECORD
    s = dz.spec
    assert (s.region_offset, s.old_region, s.new_region) == (0, przed[:2880], po[:2880])
    assert (s.write_start, s.write_end) == (koniec, koniec + 83)       # karta + „END” niżej
    assert writeback.RegionBackup.decode(dz.backup_text).region == przed[:2880]
    assert dz.fazy == ["written"]


# ============================================================ ORKIESTRACJA: commit / undo / odzysk


@pytest.mark.parametrize("plik", [
    pytest.param(lambda tp: _fits_bez(tp / "a.fits"), id="karta_w_miejscu_END"),
    pytest.param(lambda tp: _fits_bez(tp / "a.fits", karty=[("IMAGETYP", "Light"),
                                                           ("HISTORY", "h1"), ("HISTORY", "h2")]),
                 id="karta_przed_HISTORY"),
])
def test_commit_i_undo_add_w_miejscu_bajt_w_bajt(tmp_path, plik):
    """`commit(inplace=True)` dopisuje kartę W MIEJSCU (operacja `commit` → `synced`, zeznanie
    z kartą, ten sam `st_ino`); `undo` W MIEJSCU zdejmuje ją i przywraca `END` - sha1 CAŁEGO pliku
    == sprzed commitu, operacja `undo` → `synced`; drugie `undo` rozpoznaje „już cofnięte”."""
    p = plik(tmp_path)
    przed = _sha1(p)
    ino = os.stat(p).st_ino
    con, loc = _baza_z_add(tmp_path, p)
    res = writeback.commit(con, "R", now=NOW, inplace=True)
    assert len(res.applied) == 1 and res.in_place == res.applied and not res.failed, res
    assert [tuple(o)[1:] for o in _operacje(con)] == [("commit", "synced")]
    assert con.execute("SELECT object_raw FROM header WHERE frame_id=?",
                       (loc["frame_id"],)).fetchone()[0] == "NGC 7635"
    assert os.stat(p).st_ino == ino and _sha1(p) != przed
    ures = writeback.undo(con, res.commit_id, now=NOW)
    assert len(ures.restored) == 1 and not ures.failed, ures
    assert _sha1(p) == przed and os.stat(p).st_ino == ino
    assert [tuple(o)[1:] for o in _operacje(con)] == [("commit", "synced"), ("undo", "synced")]
    assert _loc(con, p)["header_hash"] == loc["header_hash"]
    u2 = writeback.undo(con, res.commit_id, now=NOW)
    assert len(u2.blocked) == 1 and "już cofnięte" in u2.blocked[0].reason
    con.close()


def test_przerwany_zapis_add_odzysk_stanu_posredniego_bajt_w_bajt(tmp_path, monkeypatch):
    """Zapis `add` w miejscu przerwany (weryfikacja rozjechana) → operacja `unverified`, lokacja
    izolowana. Połowa zakresu zapisu wraca do starego (rozdarcie): `recover_torn` przywraca region
    bez parsowania - plik bajt w bajt, izolacja zdjęta, nagłówek w bazie sprzed zapisu."""
    p = _fits_bez(tmp_path / "arch" / "t.fits")
    przed = p.read_bytes()
    con, loc = _baza_z_add(tmp_path, p)
    _psuj_fsync(monkeypatch)
    writeback.commit(con, "R", now=NOW, inplace=True)
    monkeypatch.undo()
    op = con.execute("SELECT * FROM inplace_op").fetchone()
    assert op["phase"] == "unverified" and scan._isolated(con, str(p))
    a, b = op["write_start"], op["write_end"]
    assert b - a > 80                                    # karta + przesunięty `END`: dwa rekordy
    dane = bytearray(p.read_bytes())
    dane[a:(a + b) // 2] = przed[a:(a + b) // 2]
    p.write_bytes(bytes(dane))
    w = writeback.recover_torn(con, op["id"], now=NOW)
    assert w.status == "restored", w
    assert p.read_bytes() == przed and not scan._isolated(con, str(p))
    assert _loc(con, p)["header_hash"] == loc["header_hash"]
    con.close()


def test_przerwa_procesu_w_fazie_writing_add_odzysk(tmp_path, monkeypatch):
    """Proces ginie po zapisie bajtów, przed utrwaleniem fazy: operacja zostaje `writing`, a region
    jest CAŁY nowy (też stan pośredni tej operacji) - `recover_torn` przywraca plik bajt w bajt."""
    p = _fits_bez(tmp_path / "arch" / "w.fits")
    przed = p.read_bytes()
    con, loc = _baza_z_add(tmp_path, p)
    prawdziwy = os.fsync

    def _fsync(fd):
        prawdziwy(fd)
        raise _Przerwa()
    monkeypatch.setattr(writeback.os, "fsync", _fsync)
    with pytest.raises(_Przerwa):
        writeback.commit(con, "R", now=NOW, inplace=True)
    monkeypatch.undo()
    (op,) = _operacje(con)
    assert op["phase"] == "writing" and b"NGC 7635" in p.read_bytes()
    assert writeback.recover_torn(con, op["id"], now=NOW).status == "restored"
    assert p.read_bytes() == przed and not scan._isolated(con, str(p))
    con.close()


def test_add_written_dokonczenie_finish_inplace(tmp_path, monkeypatch):
    """Re-sync po zapisie `add` padł (czkawka udziału) → operacja `written`, lokacja izolowana;
    `finish_inplace` robi kontrolę danych i re-sync → `synced`, wpis stagingu 'applied', karta
    w bazie, izolacja zdjęta."""
    p = _fits_bez(tmp_path / "arch" / "f.fits")
    con, loc = _baza_z_add(tmp_path, p)
    _zerwany_udzial(monkeypatch)
    res = writeback.commit(con, "R", now=NOW, inplace=True)
    monkeypatch.undo()
    (op_id, _, faza), = [tuple(o) for o in _operacje(con)]
    assert faza == "written" and f"finish_inplace({op_id})" in res.failed[0].reason
    assert writeback.finish_inplace(con, op_id, now=NOW).status == "applied"
    assert _operacje(con)[0]["phase"] == "synced" and not scan._isolated(con, str(p))
    assert [r["status"] for r in writeback.pending_for_run(con, "R")] == ["applied"]
    assert con.execute("SELECT object_raw FROM header WHERE frame_id=?",
                       (loc["frame_id"],)).fetchone()[0] == "NGC 7635"
    con.close()


def test_dowiazanie_twarde_przezywa_add_w_miejscu_a_droga_atomowa_je_zrywa(tmp_path):
    """Sedno AR-117: dowiązanie w wydaniu `_WBPP` widzi kartę dopisaną W MIEJSCU (ten sam
    `st_ino`), a po drodze atomowej zostaje przy STAREJ treści (podmiana daje ścieżce nowy plik).
    Druga połowa dokumentuje, po co ta droga istnieje."""
    (tmp_path / "_WBPP").mkdir()
    wyniki = {}
    for droga in ("w_miejscu", "atomowa"):
        p = _fits_bez(tmp_path / f"{droga}.fits")
        link = tmp_path / "_WBPP" / p.name
        os.link(p, link)
        ino = os.stat(p).st_ino
        if droga == "w_miejscu":
            res = writeback.write_changes_inplace(str(p), [_add()], _hash(p))
            assert res.in_place
        else:
            res = writeback.write_changes(str(p), [_add()], _hash(p))
        assert res.status == "applied", res
        wyniki[droga] = (os.stat(p).st_ino == ino == os.stat(link).st_ino,
                         "OBJECT" in fits.getheader(str(link)), link.read_bytes() == p.read_bytes())
    assert wyniki == {"w_miejscu": (True, True, True), "atomowa": (False, False, False)}


# ============================================================ WIELE HDU


def _dwa_hdu(path, wariant):
    """`pusty_primary`: PrimaryHDU z `NAXIS = 0` + obraz w rozszerzeniu - nagłówek wybranego HDU
    (`scan._select_hdu`) zaczyna się za pierwszym blokiem (niezerowy `region_start`).
    `obraz_i_rozszerzenie`: obraz w PrimaryHDU + rozszerzenie z danymi za nim."""
    obraz = (np.arange(64 * 64) % 3000).astype(np.int16).reshape(64, 64)
    if wariant == "pusty_primary":
        prim = fits.PrimaryHDU()
        prim.header["ORIGIN"] = "test"
        ext = fits.ImageHDU(data=obraz, name="OBRAZ")
        ext.header["IMAGETYP"] = "Light"
    else:
        prim = fits.PrimaryHDU(data=obraz)
        prim.header["IMAGETYP"] = "Light"
        ext = fits.ImageHDU(data=np.full((64, 64), 3, dtype=np.int16), name="DRUGI")
    fits.HDUList([prim, ext]).writeto(path, overwrite=True)
    return path


@pytest.mark.parametrize("wariant, wybrany", [("pusty_primary", 1), ("obraz_i_rozszerzenie", 0)])
def test_add_w_miejscu_w_naglowku_wybranego_HDU_i_undo_bajt_w_bajt(tmp_path, wariant, wybrany):
    """Karta trafia do nagłówka HDU wybranego przez skan (`_select_hdu`: pierwsze z obrazem), także
    gdy zaczyna się on za pierwszym blokiem pliku. Bajty poza nagłówkiem tego HDU (inne HDU,
    dane) nietknięte, offset danych i rozmiar bez zmian, operacja niesie offset regionu, a undo
    oddaje sha1 CAŁEGO pliku sprzed commitu."""
    p = _dwa_hdu(tmp_path / f"{wariant}.fits", wariant)
    przed = p.read_bytes()
    with fits.open(str(p)) as h:
        indeks, _ = scan._select_hdu(h)
        info = h.fileinfo(indeks)
    start, dane = info["hdrLoc"], info["datLoc"]
    assert indeks == wybrany and (start > 0) == (wariant == "pusty_primary")
    con, loc = _baza_z_add(tmp_path, p)
    res = writeback.commit(con, "R", now=NOW, inplace=True)
    assert res.in_place == res.applied and len(res.applied) == 1, res
    po = p.read_bytes()
    assert len(po) == len(przed) and po[:start] == przed[:start] and po[dane:] == przed[dane:]
    assert con.execute("SELECT region_offset FROM inplace_op").fetchone()[0] == start
    with fits.open(str(p)) as h:
        assert h.fileinfo(indeks)["datLoc"] == dane
        assert [("OBJECT" in hdu.header) for hdu in h] == [i == indeks for i in range(len(h))]
    ures = writeback.undo(con, res.commit_id, now=NOW)
    assert len(ures.restored) == 1, ures
    assert p.read_bytes() == przed
    con.close()


# ============================================================ DROGA header-fix (CLI) na mieszance


def test_header_fix_mieszanka_w_miejscu_spadek_i_set_potem_undo_bajt_w_bajt(tmp_path, capsys):
    """`horreum header-fix` (`commit(inplace=True)`) dopisuje kartę `FILTER` dowolnemu FITS-owi
    z folderu filtra - zmiana jest ogólna, nie tylko `OBJECT`. Mieszanka jednego przebiegu:
    light FITS z zapasem nagłówka (`add` W MIEJSCU), light FITS bez zapasu (`add` → spadek na drogę
    atomową, nowy `st_ino`) i master XISF (`set` IMAGETYP + `add` FILTER w miejscu). Wynik per
    plik, potem `--undo` całego commitu: każdy plik bajt w bajt sprzed zapisu."""
    dbp, master, light, osc = _archiwum(tmp_path)
    ciasny = _fits_bez(tmp_path / "ASTRO_" / "LIGHTS" / "NGC3034" / "RC8_2600MC" / "L-Pro"
                       / "L3.fits", karty=[("IMAGETYP", "Light"), ("TELESCOP", "RC8"),
                                           ("INSTRUME", "ZWO ASI2600MC Pro"), ("XBINNING", 1),
                                           ("XPIXSZ", 3.76), ("BAYERPAT", "RGGB"),
                                           ("DATE-OBS", "2022-04-21T22:05:00"), ("EXPTIME", 300.0)],
                       zapas=0, seed=5)
    con = db.open_db(dbp)
    scan.ingest_record(con, scan.scan_file(str(ciasny)), volume="V", now=NOW,
                       summary=scan.ScanSummary())
    cli._pochodne(con, NOW, [])
    con.close()
    pliki = [master, light, str(ciasny)]
    bajty = {p: open(p, "rb").read() for p in pliki}
    ino = {p: os.stat(p).st_ino for p in pliki}

    kod, out = _cli(capsys, "header-fix", dbp)
    assert kod == 0 and "zmiany 4 kart w 3 kopiach" in out, out
    kod, out = _cli(capsys, "header-fix", dbp, "--apply", "--plan", _plan(out))
    assert kod == 0 and "zapisane 3 (w miejscu 2)" in out, out
    assert all(_karty(p)["FILTER"] == "L-Pro" for p in pliki)
    assert _karty(master)["IMAGETYP"] == "Master Flat"
    assert {p: os.stat(p).st_ino == ino[p] for p in pliki} == {
        master: True, light: True, str(ciasny): False}
    commit = re.search(r"--undo (\d+)", out).group(1)

    kod, out = _cli(capsys, "header-fix", dbp, "--undo", commit)
    assert kod == 0 and "przywrocone 3" in out, out
    assert {p: open(p, "rb").read() == b for p, b in bajty.items()} == dict.fromkeys(pliki, True)


# ============================================================ PODGLĄD DROGI (`inplace_route`)


def test_przewidywanie_drogi_add_mowi_zalezy_od_pliku(tmp_path):
    """`inplace_route(op="add")` nie obiecuje zapisu w miejscu: zapas nagłówka nie jest faktem
    bazy, więc mieszcząca się karta dostaje powód „zależy od pliku”, a rozstrzyga pisarz - plik
    z zapasem w miejscu, bez zapasu spadek. `set` bez zmian; karta, która się nie mieści, dostaje
    swój powód; karta liczbowa (AR-261) - ta sama reguła co tekstowa; XISF → `None`."""
    powod = writeback.inplace_route("fits", "OBJECT", "NGC 7635", "str", None, op="add")
    assert powod is not None and powod.startswith("zależy od pliku")
    z = _fits_bez(tmp_path / "z.fits")
    bez = _fits_bez(tmp_path / "b.fits", zapas=0)
    assert writeback.write_changes_inplace(str(z), [_add()], _hash(z)).in_place
    assert isinstance(writeback.write_changes_inplace(str(bez), [_add()], _hash(bez)),
                      writeback.Fallback)
    assert writeback.inplace_route("fits", "OBJECT", "NGC 7635", "str", None) is None
    nie_miesci = writeback.inplace_route("fits", "OBJECT", "V" * 20, "str", "k" * 60, op="add")
    assert nie_miesci == writeback._fits_card_image("OBJECT", "V" * 20, "k" * 60)[1]
    assert writeback.inplace_route("fits", "FOCALLEN", "800", "int", None,
                                   op="add").startswith("zależy od pliku")
    assert writeback.inplace_route("xisf", "OBJECT", "NGC 7635", "str", None, op="add") is None


# ============================================================ PROGNOZA DROGI Z LUSTRA KART (AR-155)


def _lustro(path):
    """Lustro kart tak, jak buduje je skan (`scan._parse_cards` po `hdr.cards`) - wiersze tabeli
    `cards` w kształcie, który podaje `queries.present_copy_card_mirror`."""
    with fits.open(str(path), mode="readonly", memmap=False) as h:
        return tuple((c.keyword, c.value_raw, c.value_type, c.comment)
                     for c in scan._parse_cards(h[0].header))


def _pad(n):
    return [f"PAD{i:<5d}= {i:20d}" for i in range(n)]


# Układ nagłówka → (prognoza: None = w miejscu | kod powodu, droga pisarza na pliku | None = bez
# przypięcia, bo prognoza i tak mówi „zależy od pliku”). Rekordów przed END w `_fits_z_bajtow`:
# 5 obowiązkowych + linie; pełny blok = 35 przed END.
_UKLADY = {
    "wolny_rekord": (lambda p: _fits_bez(p, zapas=1), None, "inplace"),
    "pelny_blok_bez_pustych": (lambda p: _fits_bez(p, zapas=0), "fb_no_room", "atomic"),
    "pusta_na_koncu_pelny_blok": (lambda p: _fits_bez(p, puste=1, zapas=0), "route_depends",
                                  "inplace"),
    "pusta_w_srodku_pelny_blok": (lambda p: _fits_z_bajtow(p, ["IMAGETYP= 'Light'", ""] + _pad(28)),
                                  "route_depends", "atomic"),
    "pusta_w_srodku_wolny_rekord": (lambda p: _fits_z_bajtow(p, ["IMAGETYP= 'Light'", ""] + _pad(5)),
                                    None, "inplace"),
    "comment_history_wolny_rekord": (
        lambda p: _fits_bez(p, karty=(("COMMENT", "a"), ("COMMENT", "b"), ("HISTORY", "c"),
                                      ("HISTORY", "d"), ("IMAGETYP", "Light")), zapas=2),
        None, "inplace"),
    "comment_history_pelny_blok": (
        lambda p: _fits_bez(p, karty=(("COMMENT", "a"), ("COMMENT", "b"), ("HISTORY", "c"),
                                      ("IMAGETYP", "Light")), zapas=0),
        "fb_no_room", "atomic"),
    "continue_wolny_rekord": (lambda p: _fits_bez(p, karty=(("NOTE", "x" * 100),), zapas=3),
                              "route_depends", None),
    # 35 kart lustra (z END byłby pełny blok), ale karta z kontynuacją zajmuje 2 rekordy -
    # reguła „liczba kart + END” skłamałaby „cały plik”.
    "continue_35_kart": (lambda p: _fits_bez(p, karty=(("NOTE", "x" * 100),), zapas=0),
                         "route_depends", "inplace"),
    "comment_z_kontynuacja_w_lustrze": (
        lambda p: _fits_z_bajtow(p, ["COMMENT " + "c" * 72, "CONTINUE  'x'"] + _pad(2)),
        "route_depends", None),
}


@pytest.mark.parametrize("uklad", sorted(_UKLADY))
def test_prognoza_drogi_dopisania_z_lustra_kart_zgodna_z_pisarzem(tmp_path, uklad):
    """AR-155: podgląd „Zmień obiekt…” przewiduje drogę dopisania karty per pozycja z lustra kart.
    Lustro buduje się po `hdr.cards`, nie po rekordach 80 B: precyzyjna prognoza („w miejscu”,
    „cały plik” z powodem pisarza `fb_no_room`, to samo zdanie i parametry) wyłącznie tam, gdzie
    lustro dowodzi układu rekordów; pusta karta przy pełnym bloku (pisarz zużyje ją tylko na
    KOŃCU) i karta z kontynuacją CONTINUE - „zależy od pliku”. Prawda = pisarz na pliku
    (`write_changes_inplace`)."""
    budowa, prognoza, droga = _UKLADY[uklad]
    p = budowa(tmp_path / f"{uklad}.fits")
    powod = writeback.inplace_route("fits", "OBJECT", "NGC 7635", "str", None, op="add",
                                    cards=_lustro(p))
    assert (None if powod is None else powod.code) == prognoza
    wynik = writeback.write_changes_inplace(str(p), [_add()], _hash(p))
    zapis = ("atomic" if isinstance(wynik, writeback.Fallback)
             else "inplace" if wynik.status == "applied" and wynik.in_place else wynik.status)
    if droga is not None:
        assert zapis == droga
    if prognoza == "fb_no_room":                       # to samo zdanie i fakty, które poda pisarz
        assert (str(wynik.reason), wynik.reason.code, wynik.reason.params) == (
            str(powod), powod.code, powod.params)


def test_prognoza_bez_lustra_mowi_zalezy_od_pliku():
    """Brak lustra (kopia bez kart w bazie, lustro innej kopii - `None` z
    `present_copy_card_mirror`) i lustro puste: dzisiejsze „zależy od pliku”, nie obietnica."""
    for cards in (None, ()):
        powod = writeback.inplace_route("fits", "OBJECT", "NGC 7635", "str", None, op="add",
                                        cards=cards)
        assert powod.code == "route_depends"
    # Karta, która się nie mieści, i XISF - jak bez lustra (lustro nie zmienia innych reguł).
    lustro = (("SIMPLE", "T", "bool", None),)
    assert writeback.inplace_route("fits", "OBJECT", "V" * 20, "str", "k" * 60, op="add",
                                   cards=lustro).code == "fb_card_too_long"
    assert writeback.inplace_route("xisf", "OBJECT", "NGC 7635", "str", None, op="add",
                                   cards=lustro) is None


# ============================================================ AR-257: odmowa łaty w planie, bez spadku


def test_plan_w_miejscu_odmawia_add_obecnej_karty_bez_spadku(tmp_path):
    """AR-257: `add` karty, która już jest - plan w miejscu odmawia OD RAZU tym samym powodem co
    droga atomowa (`macro_add_exists`), zamiast spadku `fb_card_present`, po którym droga atomowa
    i tak odmawiała. Dziennik nieotwarty, plik bajt w bajt. Falsyfikator: gałąź spadku przywrócona
    → `Fallback`."""
    p = _fits_bez(tmp_path / "b.fits", karty=[("IMAGETYP", "Light"), ("OBJECT", "M31")])
    przed = p.read_bytes()
    res = writeback.write_changes_inplace(str(p), [_add()], _hash(p), journal=_NieWolno())
    assert isinstance(res, writeback.WriteResult) and res.status == "blocked", res
    assert res.reason.code == "macro_add_exists" and dict(res.reason.params) == {"keyword": "OBJECT"}
    assert res.backup_text is None and p.read_bytes() == przed


@pytest.mark.parametrize("fallback", [True, False], ids=["spadek", "pilotaz"])
def test_commit_add_obecnej_karty_jednym_przebiegiem(tmp_path, monkeypatch, fallback):
    """AR-257: `commit(inplace=True)` (op szuflady i okien) stagingiem bez kotwicy - droga atomowa
    NIE jest wołana (jeden przebieg pod blokadą zamiast dwóch), wpis 'blocked' z kodem
    `macro_add_exists` w obu trybach; tryb pilotażu mówi prawdziwy powód zamiast `no_fallback`.
    Falsyfikator: spadek przywrócony → `write_changes` wołany / kod `no_fallback`."""
    p = _fits_bez(tmp_path / "b.fits", karty=[("IMAGETYP", "Light"), ("OBJECT", "M31")])
    przed = p.read_bytes()
    con = db.open_db(str(tmp_path / "h.db"))
    _scan_in(con, p)
    _stage_add(con, "R", _loc(con, p)["id"], None)
    wolania = []
    prawdziwy = writeback.write_changes
    monkeypatch.setattr(writeback, "write_changes",
                        lambda *a, **k: wolania.append(a) or prawdziwy(*a, **k))
    res = writeback.commit(con, "R", now=NOW, inplace=True, fallback=fallback)
    (fr,) = res.blocked
    assert fr.reason.code == "macro_add_exists" and not wolania and res.commit_id is None, fr.reason
    (w,) = con.execute("SELECT status, reason_code FROM pending_changes WHERE run_id = 'R'")
    assert tuple(w) == ("blocked", "macro_add_exists")
    assert con.execute("SELECT count(*) FROM inplace_op").fetchone()[0] == 0
    assert p.read_bytes() == przed
    con.close()


def test_przebieg_probny_na_jednej_kopii_naglowka_bez_ruszania_oryginalu(tmp_path, monkeypatch):
    """AR-257 (przebieg próbny): łata idzie po kolei na JEDNEJ kopii nagłówka - druga z dwóch
    zależnych operacji (`add` tej samej karty dwa razy) widzi skutek pierwszej i odmawia tak jak droga
    atomowa (`macro_add_exists`), a nagłówek planu (oryginał z `_fits_hdu_bounds`) zostaje: obrazy
    kart i `header_hash` bez zmian. Falsyfikatory: osobna kopia na każdą operację → druga nie widzi
    pierwszej (spadek zamiast odmowy); praca na oryginale → oryginał z kartą łaty."""
    p = _fits_bez(tmp_path / "b.fits")
    przed = p.read_bytes()
    naglowki = []
    prawdziwy = writeback._fits_hdu_bounds

    def _granice(path, expected):
        wynik = prawdziwy(path, expected)
        hdr = wynik[0]
        naglowki.append((hdr, [c.image for c in hdr.cards], scan._header_hash(hdr)))
        return wynik
    monkeypatch.setattr(writeback, "_fits_hdu_bounds", _granice)
    ops = [_add("OBSERVER", "Zdzin"), _add("OBSERVER", "Ktos")]
    res = writeback.write_changes_inplace(str(p), ops, _hash(p), journal=_NieWolno())
    assert isinstance(res, writeback.WriteResult) and res.status == "blocked", res
    assert res.reason.code == "macro_add_exists" and dict(res.reason.params) == {
        "keyword": "OBSERVER"}
    ((hdr, obrazy, hash_przed),) = naglowki
    assert [c.image for c in hdr.cards] == obrazy and scan._header_hash(hdr) == hash_przed
    assert "OBSERVER" not in hdr and p.read_bytes() == przed
    atom = writeback.write_changes(str(p), ops, _hash(p))               # ta sama odmowa atomowo
    assert (atom.status, atom.reason.code) == ("blocked", "macro_add_exists")


# ============================================================ AR-261: karta liczbowa W MIEJSCU


def _rekordy_naglowka(dane):
    koniec = dane.index(writeback._FITS_END_RECORD)
    blok = -(-(koniec // 80 + 1) * 80 // 2880) * 2880
    return [dane[i:i + 80] for i in range(0, blok, 80)]


_LICZBOWE = [("IMAGETYP", "Light"), ("FOCALLEN", 800, "ogniskowa [mm]"), ("EXPTIME", 300.0),
             ("FLIPPED", True), ("GAIN", 0), ("SETTEMP", 0.0)]


def _op(kw, op, wartosc, typ, comment=None):
    return writeback.WriteOp(kw, op, wartosc, typ, idx=0 if op == "set" else None, comment=comment)


@pytest.mark.parametrize("op", [
    pytest.param(_op("FOCALLEN", "set", "1000", "int"), id="int"),
    pytest.param(_op("FOCALLEN", "set", str(2 ** 62 + 1), "int"), id="int_duzy"),
    pytest.param(_op("EXPTIME", "set", "1.5e-05", "float"), id="float_wykladniczy"),
    pytest.param(_op("EXPTIME", "set", "-0.0", "float"), id="float_minus_zero"),
    pytest.param(_op("GAIN", "set", "-0.0", "float"), id="minus_zero_na_int_zero"),
    pytest.param(_op("SETTEMP", "set", "-0.0", "float"), id="minus_zero_na_float_zero"),
    pytest.param(_op("EXPTIME", "set", repr(-1.2345678901234567e-300), "float"),
                 id="float_dluzszy_niz_pole"),
    pytest.param(_op("FLIPPED", "set", "F", "bool"), id="bool"),
    pytest.param(_op("FOCALLEN", "set", "1000", "int", comment="nowy komentarz"), id="komentarz"),
    pytest.param(_op("FOCALLEN", "set", "800", "int"), id="ta_sama_wartosc"),
    pytest.param(_op("EXPTIME", "set", "60", "int"), id="int_na_float"),
    pytest.param(_op("FOCALLEN", "set", "1000.5", "float"), id="float_na_int"),
    pytest.param(_op("XBINNING", "add", "2", "int"), id="add_int"),
    pytest.param(_op("CCD-TEMP", "add", "-10.1", "float", comment="C"), id="add_float"),
    pytest.param(_op("SIMULATE", "add", "T", "bool"), id="add_bool"),
])
def test_karta_liczbowa_w_miejscu_bajt_w_bajt_jak_droga_atomowa(tmp_path, op):
    """AR-261 człon 1: karta liczbowa i logiczna idzie W MIEJSCU (dawniej zawsze spadek `fb_op_kind`
    - przepisanie całego pliku zrywało dowiązanie `_WBPP`). Plik w miejscu == plik drogi atomowej
    BAJT W BAJT (dokładne 80 B rekordu karty i cały region, dane), ten sam `st_ino`. Zakres zmiany:
    `set` - jeden rekord (karta wartości równej zastanej wg reguły astropy, np. `-0.0` na `0.0`,
    `800` na `800` - zero; `-0.0` na int `0` to zmiana typu); `add` - ciąg od miejsca wstawienia do
    przesuniętego `END`, reszta nietknięta.
    Float dłuższy niż pole karty traci cyfry w OBU drogach jednakowo (znalezisko poza tym punktem).
    Falsyfikatory: `value_type != "str"` z powrotem w spadku → `Fallback`; obraz z `fits.Card` dla
    karty, której astropy nie przełożył → `-0.0`/ta sama wartość różnią się od atomu."""
    p = _fits_bez(tmp_path / "n.fits", karty=_LICZBOWE)
    przed = p.read_bytes()
    ra, rw, atom, wm, ino = _dwie_drogi(p, [op])
    assert ra.status == "applied", ra
    assert isinstance(rw, writeback.WriteResult) and rw.status == "applied" and rw.in_place, rw
    assert os.stat(wm).st_ino == ino and wm.read_bytes() == atom.read_bytes()
    stare, nowe = _rekordy_naglowka(przed), _rekordy_naglowka(wm.read_bytes())
    assert len(stare) == len(nowe) and wm.read_bytes()[len(nowe) * 80:] == przed[len(stare) * 80:]
    inne = [i for i, (a, b) in enumerate(zip(stare, nowe)) if a != b]
    kw = op.keyword.ljust(8).encode("ascii")
    if op.op == "set":
        cel = [i for i, r in enumerate(stare) if r[:8] == kw]
        assert inne in ([], cel), (inne, cel)
        assert inne or op.value in ("800", "-0.0"), inne         # bez zmiany tylko wartość równa
    else:
        koniec = nowe.index(writeback._FITS_END_RECORD)
        assert inne == list(range(inne[0], koniec + 1)) and nowe[inne[0]][:8] == kw, inne
    assert scan.read_fits_meta(str(wm)).header_hash == rw.post_hash


@pytest.mark.parametrize("zastana, op, kod", [
    pytest.param(("FOCALLEN", 800), _op("FOCALLEN", "set", "789", "str"), "fb_value_not_text",
                 id="tekst_na_liczbie"),
    pytest.param(("FLIPPED", True), _op("FLIPPED", "set", "F", "str"), "fb_value_not_text",
                 id="tekst_na_logice"),
    pytest.param(("TELESCOP", "RC8"), _op("TELESCOP", "set", "8", "int"), "fb_op_kind",
                 id="liczba_na_tekscie"),
    pytest.param(("FLIPPED", True), _op("FLIPPED", "set", "1", "int"), "fb_op_kind",
                 id="liczba_na_logice"),
    pytest.param(("TELESCOP", "RC8"), _op("TELESCOP", "set", "T", "bool"), "fb_op_kind",
                 id="logika_na_tekscie"),
    pytest.param(("FOCALLEN", 800), _op("FOCALLEN", "set", "T", "bool"), "fb_op_kind",
                 id="logika_na_liczbie"),
])
def test_zapis_innego_rodzaju_niz_zastana_karta_spada_na_droge_atomowa(tmp_path, zastana, op, kod):
    """AR-261: w miejscu wyłącznie przy ZGODNYM rodzaju wartości (tekst / logika / liczba, int i float
    to jeden rodzaj - `bool` rozpoznany PRZED `int`, bo jest jego podklasą); sześć zmian rodzaju
    spada przed dziennikiem, plik nietknięty. Falsyfikatory: kontrola rodzaju zdjęta → zapis w miejscu
    ze zmianą typu karty; `bool` klasyfikowany jako liczba → `logika_na_liczbie`/`liczba_na_logice`
    w miejscu."""
    p = _fits_bez(tmp_path / "r.fits", karty=[("IMAGETYP", "Light"), zastana])
    przed = p.read_bytes()
    res = writeback.write_changes_inplace(str(p), [op], _hash(p), journal=_NieWolno())
    assert isinstance(res, writeback.Fallback) and res.reason.code == kod, res
    assert p.read_bytes() == przed


@pytest.mark.parametrize("wartosc", ["nan", "inf"])
def test_nan_i_inf_ta_sama_porazka_obu_drog_bez_zmiany_pliku(tmp_path, wartosc):
    """AR-261: wartości, której karta FITS nie zniesie (`nan`, `inf` - astropy rzuca), obie drogi
    odmawiają TĄ SAMĄ porażką ('failed' z tekstem astropy) przed jakimkolwiek zapisem: plik bajt
    w bajt, bez pliku tymczasowego, dziennik nieotwarty. Falsyfikator: obraz liczony bez przebiegu
    próbnego w innym miejscu niż droga atomowa → inny tekst albo zapis."""
    p = _fits_bez(tmp_path / "x.fits", karty=_LICZBOWE)
    przed = p.read_bytes()
    op = _op("EXPTIME", "set", wartosc, "float")
    rw = writeback.write_changes_inplace(str(p), [op], _hash(p), journal=_NieWolno())
    ra = writeback.write_changes(str(p), [op], _hash(p))
    assert (rw.status, ra.status) == ("failed", "failed") and str(rw.reason) == str(ra.reason), (
        rw, ra)
    assert "not allowed in FITS headers" in str(rw.reason)
    assert p.read_bytes() == przed and sorted(x.name for x in tmp_path.iterdir()) == ["x.fits"]


def test_dowiazanie_twarde_przezywa_zapis_karty_liczbowej_i_cofniecie(tmp_path):
    """AR-261 sedno: `commit(inplace=True)` karty liczbowej (`set FOCALLEN 1000`) - dowiązanie twarde
    (wydanie `_WBPP`) widzi nową wartość, plik ten sam węzeł, zapis w miejscu (`in_place`, operacja
    w dzienniku), a „Cofnij” w miejscu oddaje plik bajt w bajt i dowiązanie dalej ten sam węzeł.
    Falsyfikator: karta liczbowa z powrotem w spadku → dowiązanie przy 800, nowy węzeł."""
    p = _fits_bez(tmp_path / "arch" / "a.fits", karty=_LICZBOWE)
    link = tmp_path / "_WBPP" / "a.fits"
    link.parent.mkdir()
    os.link(p, link)
    przed, ino = p.read_bytes(), os.stat(p).st_ino
    con = db.open_db(str(tmp_path / "h.db"))
    _scan_in(con, p)
    loc = _loc(con, p)
    repo.stage_pending(con, run_id="R", location_id=loc["id"], keyword="FOCALLEN", idx=0, op="set",
                       old_value="800", new_value="1000", new_type="int", new_comment=None,
                       expected_header_hash=loc["header_hash"])
    res = writeback.commit(con, "R", now=NOW, inplace=True)
    assert len(res.applied) == 1 and res.in_place == res.applied, res
    assert fits.getheader(str(link))["FOCALLEN"] == 1000
    assert os.stat(p).st_ino == os.stat(link).st_ino == ino
    assert [tuple(o)[1:] for o in _operacje(con)] == [("commit", "synced")]
    ures = writeback.undo(con, res.commit_id, now=NOW)
    assert len(ures.restored) == 1 and not ures.failed, ures
    assert p.read_bytes() == przed == link.read_bytes() and os.stat(link).st_ino == ino
    con.close()


@pytest.mark.parametrize("rekord, op, format_zostaje", [
    pytest.param("OBJECT  = 'M31                 ' / stary komentarz",
                 _op("OBJECT", "set", "M31", "str", comment="nowy komentarz"), True,
                 id="tekst_dopelniony_sam_komentarz"),
    pytest.param("FOCRATIO=              1.0E+00 / stary komentarz",
                 _op("FOCRATIO", "set", "1.0", "float", comment="nowy komentarz"), True,
                 id="liczba_wykladnicza_sam_komentarz"),
    pytest.param("EXPTIME =                 600. / stary komentarz",
                 _op("EXPTIME", "set", "600.0", "float", comment="nowy komentarz"), False,
                 id="liczba_z_kropka_sam_komentarz"),
    pytest.param("FOCRATIO=              1.0E+00 / stary komentarz",
                 _op("FOCRATIO", "set", "2.5", "float"), False,
                 id="liczba_wykladnicza_nowa_wartosc"),
    pytest.param("OBJECT  = 'M31                 ' / stary komentarz",
                 _op("OBJECT", "set", "M 31", "str"), False, id="tekst_dopelniony_nowa_wartosc"),
])
def test_karta_o_zastanym_formacie_wartosci_w_miejscu_bajt_w_bajt_jak_droga_atomowa(
        tmp_path, rekord, op, format_zostaje):
    """AR-261: rekord w formacie wartości INNYM niż świeża karta astropy (tekst dopełniony spacjami
    w apostrofach, liczba wykładnicza `1.0E+00`, liczba `600.`). Przy zmianie SAMEGO komentarza
    astropy zachowuje zastany format wartości tekstu dopełnionego i `1.0E+00` (`600.` przekłada po
    swojemu), przy zmianie wartości - układa ją po swojemu; plik w miejscu == plik drogi atomowej BAJT
    W BAJT (ta sama karta po `_apply_op`, nie świeża `fits.Card`), jeden zmieniony rekord.
    Falsyfikator: obraz karty ze świeżej `fits.Card` → zmiana samego komentarza 'failed' (obraz inny
    niż karta drogi atomowej) albo inne bajty."""
    p = _fits_z_bajtow(tmp_path / "f.fits", ["IMAGETYP= 'Light   '", rekord])
    przed = p.read_bytes()
    ra, rw, atom, wm, ino = _dwie_drogi(p, [op])
    assert ra.status == "applied", ra
    assert isinstance(rw, writeback.WriteResult) and rw.status == "applied" and rw.in_place, rw
    assert os.stat(wm).st_ino == ino and wm.read_bytes() == atom.read_bytes()
    stare, nowe = _rekordy_naglowka(przed), _rekordy_naglowka(wm.read_bytes())
    assert [i for i, (a, b) in enumerate(zip(stare, nowe)) if a != b] == [6], (stare[6], nowe[6])
    if format_zostaje:
        assert nowe[6][:30] == stare[6][:30], nowe[6]                     # format wartości zostaje
    assert fits.getheader(str(wm)).comments[op.keyword] == (op.comment or "stary komentarz")
