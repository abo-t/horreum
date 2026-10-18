"""`horreum header-fix --undo` mówi faktami rdzenia cofnięcia (`UndoResult.already`, `complete`):
plik „już cofnięty” ma własny wiersz i nie liczy się do zablokowanych, a kod wyjścia znaczy
„cofnięcie niedomknięte” - ta sama reguła co uchwyt „Cofnij” okien kart (AR-160). Dawniej każda
blokada, także „już cofnięte”, dawała licznik „zablokowane” i kod 1, więc ponowienie domkniętego
cofnięcia wyglądało jak porażka. Prawdziwe pliki FITS i XISF w `tmp_path` (archiwum `test_header_fix`)."""
from __future__ import annotations

import re

from astropy.io import fits

from test_header_fix import _archiwum, _cli, _plan


def _zapis(tmp_path, capsys):
    """Archiwum po `header-fix --apply`: `(baza, light FITS, numer commitu)` - zapis 2 plików."""
    dbp, _master, light, _osc = _archiwum(tmp_path)
    _kod, out = _cli(capsys, "header-fix", dbp)
    kod, out = _cli(capsys, "header-fix", dbp, "--apply", "--plan", _plan(out))
    assert kod == 0 and "zapisane 2" in out, out
    return dbp, light, re.search(r"--undo (\d+)", out).group(1)


def test_ponowione_undo_juz_cofniete_osobnym_wierszem_i_kod_zero(tmp_path, capsys):
    """Drugie `--undo` domkniętego cofnięcia: oba pliki „już cofnięte” - zero zablokowanych, własny
    wiersz z liczbą, bez wierszy plików, kod 0. Falsyfikator: kod z `res.blocked or res.failed` →
    1; licznik z całego `res.blocked` → „zablokowane 2”."""
    dbp, _light, commit = _zapis(tmp_path, capsys)
    kod, out = _cli(capsys, "header-fix", dbp, "--undo", commit)
    assert kod == 0 and "przywrocone 2" in out and "juz cofniete" not in out, out
    kod, out = _cli(capsys, "header-fix", dbp, "--undo", commit)
    assert kod == 0, out
    assert "przywrocone 0 (bez powrotu zeznania 0), zablokowane 0, nieudane 0" in out, out
    assert "\n  juz cofniete 2 - wynik cofniecia jest juz na dysku i w bazie" in out, out
    assert "    blocked: " not in out, out


def test_undo_z_plikiem_zmienionym_od_commitu_zostaje_niedomkniete(tmp_path, capsys):
    """Light zmieniony po commicie: pierwsze `--undo` przywraca drugi plik, light zablokowany (kod 1);
    ponowienie - jeden „już cofnięty” osobno, jeden zablokowany z wierszem pliku, kod dalej 1.
    Falsyfikator: kod 0 przy blokadzie spoza `already` albo light liczony do „już cofniętych”."""
    dbp, light, commit = _zapis(tmp_path, capsys)
    fits.setval(light, "TELESCOP", value="Inny")                    # cudza zmiana po commicie
    kod, out = _cli(capsys, "header-fix", dbp, "--undo", commit)
    assert kod == 1 and "przywrocone 1" in out and "zablokowane 1" in out, out
    assert "juz cofniete" not in out, out
    kod, out = _cli(capsys, "header-fix", dbp, "--undo", commit)
    assert kod == 1 and "zablokowane 1" in out and "\n  juz cofniete 1 - " in out, out
    assert f"    blocked: {light} - " in out, out


def _undo_z_wynikiem(tmp_path, capsys, monkeypatch, wynik, *argv):
    """`header-fix --undo 7` z wynikiem rdzenia podstawionym pod `writeback.undo` - liczniki, wiersze
    i kod wyjścia CLI dla każdej kombinacji `UndoResult` bez budowania jej na plikach."""
    from horreum import db, writeback
    dbp = str(tmp_path / "u.db")
    db.open_db(dbp).close()
    monkeypatch.setattr(writeback, "undo", lambda con, commit_id, now: wynik)
    return _cli(capsys, "header-fix", dbp, "--undo", "7", *argv)


def test_undo_nieudane_wiersz_na_plik_z_limitem_i_kod_jeden(tmp_path, capsys, monkeypatch):
    """Pliki nieudane (błąd systemu klasą): licznik „nieudane N”, wiersz na plik ze zdaniem PL z numerem,
    `--limit` ucina wiersze (nie licznik), kod 1 - cofnięcie niedomknięte."""
    from horreum import writeback
    from horreum.item_reasons import blad_systemu
    powod = blad_systemu(OSError(None, "Nazwa sieciowa jest już niedostępna", r"X:\L\a.fits", 64))
    padle = [writeback.FileResult(i, rf"X:\L\{i}.fits", "failed", powod) for i in (1, 2, 3)]
    kod, out = _undo_z_wynikiem(tmp_path, capsys, monkeypatch,
                                writeback.UndoResult(7, [], [], padle), "--limit", "2")
    assert kod == 1, out
    assert "przywrocone 0 (bez powrotu zeznania 0), zablokowane 0, nieudane 3" in out, out
    wiersze = [w for w in out.splitlines() if w.startswith("    failed: ")]
    assert wiersze == [rf"    failed: X:\L\{i}.fits - udział sieciowy albo dysk nie odpowiada (WinError 64)"
                       for i in (1, 2)], out
    out.encode("cp1250")


def test_undo_przerwane_bez_plikow_kod_jeden(tmp_path, capsys, monkeypatch):
    """Cofnięcie przerwane na żądanie (`cancelled`) przed pierwszym backupem: same zera, żadnego wiersza
    pliku, kod 1 - ponowienie ma co sprawdzić."""
    from horreum import writeback
    kod, out = _undo_z_wynikiem(tmp_path, capsys, monkeypatch,
                                writeback.UndoResult(7, [], [], [], cancelled=True, remaining=2))
    assert kod == 1, out
    assert "przywrocone 0 (bez powrotu zeznania 0), zablokowane 0, nieudane 0" in out, out
    assert "    failed: " not in out and "    blocked: " not in out and "juz cofniete" not in out, out


def test_undo_bez_backupow_zera_i_kod_zero(tmp_path, capsys, monkeypatch):
    """Commit bez backupów (nic do cofnięcia): same zera, bez wierszy, kod 0 - cofnięcie domknięte."""
    from horreum import writeback
    kod, out = _undo_z_wynikiem(tmp_path, capsys, monkeypatch, writeback.UndoResult(7, [], [], []))
    assert kod == 0, out
    assert out.strip() == (f"Horreum header-fix {tmp_path / 'u.db'} (UNDO commit 7): przywrocone 0 "
                           f"(bez powrotu zeznania 0), zablokowane 0, nieudane 0"), out


def test_undo_po_zmianie_od_commitu_ponowienie_mowi_neutralnie(tmp_path, capsys):
    """AR-182 na prawdziwym commicie atomowym: drugie HDU zmienione od commitu - `--undo`
    przywraca nagłówek (zmiana zostaje w pliku), kod 0; ponowne `--undo` - plik „już cofnięty”
    wynikiem własnym, wiersz NIE twierdzi, że na dysku jest stan sprzed commitu (nieprawda: obca
    zmiana została), kod z `complete` = 0, ASCII pod cp1250. Falsyfikator: dawne zdanie „stan sprzed
    commitu jest juz na dysku”."""
    from horreum import writeback
    from test_powody_pisarza import _fits_dwa_hdu
    from test_writeback_inplace import NOW, _baza_z_plikiem
    p = _fits_dwa_hdu(tmp_path / "d.fits")
    con, _ = _baza_z_plikiem(tmp_path, p)
    res = writeback.commit(con, "R", now=NOW)
    assert len(res.applied) == 1 and not res.in_place, res
    con.close()
    dane = bytearray(p.read_bytes())
    i = dane.index(b"'aaaa ")
    dane[i:i + 5] = b"'bbbb"
    p.write_bytes(bytes(dane))
    dbp = str(tmp_path / "h.db")
    kod, out = _cli(capsys, "header-fix", dbp, "--undo", str(res.commit_id))
    assert kod == 0 and "przywrocone 1" in out and "juz cofniete" not in out, out
    assert b"'bbbb" in p.read_bytes() and fits.getheader(str(p))["OBJECT"] == "NGC6992"
    kod, out = _cli(capsys, "header-fix", dbp, "--undo", str(res.commit_id))
    assert kod == 0, out
    assert "\n  juz cofniete 1 - wynik cofniecia jest juz na dysku i w bazie" in out, out
    assert "stan sprzed commitu" not in out, out
    out.encode("cp1250")


def test_undo_backupu_tekstowego_przyjetego_skanem_mowi_granice(tmp_path, capsys):
    """AR-229: commit sprzed kopert (backup tekstowy) cofnięty raz, potem wynik zmieniony poza
    nagłówkiem i przyjęty skanem - `--undo` kończy się kodem 0, a wiersz „już cofnięte” mówi granicę:
    nagłówek i baza opisują stan sprzed commitu, reszty pliku backup tekstowy nie pozwala sprawdzić;
    ASCII pod cp1250. Bez skanu - kod 1 i wiersz odmowy z receptą skanu. Falsyfikator: wspólny wiersz
    „wynik cofniecia jest juz na dysku” dla tego kodu."""
    import os
    from horreum import db, writeback
    from test_powody_pisarza import _fits_dwa_hdu
    from test_writeback_inplace import NOW, _scan_in, _stary_commit
    p = _fits_dwa_hdu(tmp_path / "s.fits")
    dbp = str(tmp_path / "h.db")
    con = db.open_db(dbp)
    _scan_in(con, p)
    cid = _stary_commit(con, p, "NGC 6992")
    assert writeback.undo(con, cid, now=NOW).complete
    st = os.stat(p)
    dane = bytearray(p.read_bytes())
    i = dane.index(b"NOTE    = '") + 11
    dane[i] ^= 0x03
    p.write_bytes(bytes(dane))
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))
    con.close()
    kod, out = _cli(capsys, "header-fix", dbp, "--undo", str(cid))
    assert kod == 1 and "blocked: " in out and "przeskanuj plik" in out, out
    out.encode("cp1250")
    con = db.open_db(dbp)
    _scan_in(con, p)
    con.close()
    kod, out = _cli(capsys, "header-fix", dbp, "--undo", str(cid))
    assert kod == 0, out
    assert out.splitlines()[1:] == ["  juz cofniete 1 - naglowek i baza opisuja stan sprzed commitu; "
                                    "reszty pliku backup tekstowy nie pozwala sprawdzic"], out
    out.encode("cp1250")


def test_undo_po_smierci_w_oknie_podmiany_mowi_pliki_do_oka(tmp_path, capsys, monkeypatch):
    """AR-127: cofnięcie zginęło po podmianie (kopia wyparta została obok ścieżki) - `--undo` raz
    blokuje lokację wierszem ze zdaniem o plikach zostawionych do oka w Porządkach i kodem 1, drugie
    `--undo` dokańcza cofnięcie z kodem 0. Kodowalność zdania pod cp1250 sprawdza test zdań na
    ścieżkach kontrolowanych (`test_writeback_cofniecie_atomowe`), nie ten przebieg - ścieżki `tmp_path`
    zależą od profilu użytkownika."""
    import pytest
    from horreum import writeback
    from test_powody_pisarza import _fits_dwa_hdu
    from test_writeback_inplace import NOW, _baza_z_plikiem

    class _Smierc(BaseException):
        pass
    p = _fits_dwa_hdu(tmp_path / "d.fits")
    con, _ = _baza_z_plikiem(tmp_path, p)
    res = writeback.commit(con, "R", now=NOW)

    def _smierc(*a, **kw):
        raise _Smierc()
    monkeypatch.setattr(writeback, "_rozjazd_odcisku", _smierc)
    with pytest.raises(_Smierc):
        writeback.undo(con, res.commit_id, now=NOW)
    monkeypatch.undo()
    con.close()
    dbp = str(tmp_path / "h.db")
    kod, out = _cli(capsys, "header-fix", dbp, "--undo", str(res.commit_id))
    zablokowane = [w for w in out.splitlines() if w.startswith("    blocked: ")]
    assert kod == 1 and len(zablokowane) == 1, out
    assert "zostawiło obok ścieżki pliki - zostają do oka w Porządkach: " in zablokowane[0], out
    kod, out = _cli(capsys, "header-fix", dbp, "--undo", str(res.commit_id))
    assert kod == 0 and "przywrocone 1" in out, out
