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
    assert "\n  juz cofniete 2 - stan sprzed commitu jest juz na dysku i w bazie" in out, out
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
