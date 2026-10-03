"""Pass obecności pod hamulcem PROGOWYM: DRY na żądanie liczy potwierdzenia (AR-31 (6)).

Kontrakt: `confirm_under_brake=True` daje w DRY liczbę POTWIERDZONĄ, którą `force` zapisze 1:1,
a sam DRY nie dotyka bazy. Hamulce „drzewo puste” / „zakres pusty” zostają odmową bez furtki,
a bez flagi DRY pod hamulcem dalej oszczędza koszt `stat` (zachowanie sprzed zmiany, CLI).

Próg obniżamy `monkeypatch` na `_BRAKE_MIN` - prawdziwy (50 kopii albo 2 % zakresu) wymagałby
setek plików FITS, a sprawdzamy klasyfikację hamulca, nie jego liczbę."""
import os
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits

from horreum import db, presence, repo
from horreum.scan import scan_tree
from horreum.volumes import volume_serial

NOW = "2026-10-03T12:00:00"
LATER = "2026-10-03T18:00:00"


def _fits(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    hdu = fits.PrimaryHDU(data=np.full((4, 4), value, dtype=np.uint16))
    hdu.header["INSTRUME"] = "ZWO ASI2600MM Pro"
    hdu.header["IMAGETYP"] = "Light Frame"
    hdu.writeto(str(path))
    return path


def _vanished_events(con):
    return con.execute("SELECT COUNT(*) FROM event WHERE verb = 'location.vanished'").fetchone()[0]


def _absent(con):
    return con.execute("SELECT COUNT(*) FROM location WHERE present = 0").fetchone()[0]


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "ASTRO"
    paths = [str(_fits(root / "LIGHTS" / f"l{i}.fits", i + 1)) for i in range(4)]
    vol = volume_serial(str(root))
    if vol is None:
        pytest.skip("volume_serial nieustalony (nie-Windows) - pass wymaga trwałego serialu")
    con = db.open_db(str(tmp_path / "h.db"))
    scan_tree(con, str(root), volume=vol, now=NOW)
    yield con, str(root), vol, paths
    con.close()


@pytest.fixture
def niski_prog(monkeypatch):
    """Próg = 1 kopia: dwa zniknięcia z czterech przekraczają go, a drzewo nie jest puste."""
    monkeypatch.setattr(presence, "_BRAKE_MIN", 1)


def test_dry_pod_hamulcem_liczy_na_zadanie_a_force_zapisuje_te_sama_liczbe(tree, niski_prog):
    con, root, vol, paths = tree
    os.remove(paths[0])
    os.remove(paths[1])
    d = presence.check(con, root, volume=vol, apply=False, confirm_under_brake=True, now=LATER)
    assert d.brake is not None and d.brake_limit == 1 and d.aborted is None
    assert d.confirmed is True and d.candidates == 2 and d.confirmed_gone == 2
    assert (d.vanished, d.run_id) == (0, None)
    assert _absent(con) == 0 and _vanished_events(con) == 0          # DRY: zero zapisu

    a = presence.check(con, root, volume=vol, apply=True, force=d.confirmed_gone, now=LATER)
    assert a.aborted is None and a.vanished == d.confirmed_gone
    assert _absent(con) == 2 and _vanished_events(con) == 2


def test_bez_flagi_dry_pod_hamulcem_nie_liczy(tree, niski_prog):
    """Zachowanie sprzed zmiany (CLI, złota akcja GUI): potwierdzeń pod hamulcem nie liczono."""
    con, root, vol, paths = tree
    os.remove(paths[0])
    os.remove(paths[1])
    d = presence.check(con, root, volume=vol, apply=False, now=LATER)
    assert d.brake_limit == 1 and d.confirmed is False and d.confirmed_gone == 0


def test_liczba_potwierdzona_to_nie_kandydaci(tree, niski_prog):
    """Kandydat, który JEDNAK istnieje (dryf casingu), nie wchodzi do liczby. Deklaracja z liczbą
    kandydatów aborciuje bez zapisu; z liczbą potwierdzoną przechodzi."""
    con, root, vol, paths = tree
    os.remove(paths[0])
    upper = str(Path(paths[1]).parent / Path(paths[1]).name.upper())
    loc = con.execute("SELECT id FROM location WHERE path = ?", (paths[1],)).fetchone()["id"]
    repo.relocate_location(con, location_id=loc, new_path=upper, now=NOW)
    d = presence.check(con, root, volume=vol, apply=False, confirm_under_brake=True, now=LATER)
    assert (d.candidates, d.confirmed_gone, d.resurfaced) == (2, 1, 1)
    zly = presence.check(con, root, volume=vol, apply=True, force=d.candidates, now=LATER)
    assert zly.aborted is not None and _absent(con) == 0
    ok = presence.check(con, root, volume=vol, apply=True, force=d.confirmed_gone, now=LATER)
    assert ok.aborted is None and ok.vanished == 1 and _absent(con) == 1


def test_drzewo_puste_zostaje_odmowa_bez_furtki(tree):
    """Każdy wiersz jest kandydatem - potwierdzona liczba byłaby deklaracją „oznacz wszystko”."""
    con, root, vol, paths = tree
    for p in paths:
        os.remove(p)
    d = presence.check(con, root, volume=vol, apply=False, confirm_under_brake=True, now=LATER)
    assert d.brake is not None and "drzewo puste" in d.brake
    assert d.brake_limit is None and d.confirmed is False and d.confirmed_gone == 0


def test_zakres_pusty_bez_limitu(tree, tmp_path):
    con, _root, vol, _paths = tree
    inny = tmp_path / "INNY"
    _fits(inny / "x.fits", 42)
    d = presence.check(con, str(inny), volume=vol, apply=False, confirm_under_brake=True, now=LATER)
    assert d.scoped == 0 and d.brake_limit is None and d.confirmed is False


def test_flaga_nie_otwiera_apply_bez_force(tree, niski_prog):
    """Furtką zapisu jest wyłącznie `force` - flaga liczenia nic nie zmienia przy `apply`."""
    con, root, vol, paths = tree
    os.remove(paths[0])
    os.remove(paths[1])
    a = presence.check(con, root, volume=vol, apply=True, confirm_under_brake=True, now=LATER)
    assert a.aborted is not None and a.vanished == 0 and _absent(con) == 0


def test_ponizej_progu_brak_limitu(tree):
    con, root, vol, paths = tree
    os.remove(paths[0])
    d = presence.check(con, root, volume=vol, apply=False, confirm_under_brake=True, now=LATER)
    assert d.brake is None and d.brake_limit is None and d.confirmed_gone == 1


# ─────────────────────── deklaracja ZBIORU z DRY (AR-31 (6), zarzuty Z4/Z6 bramki paczki)

def test_ten_sam_rozmiar_inny_zbior_aborciuje_bez_zapisu(tree, niski_prog):
    """Między DRY a zapisem jedna kopia wróciła, a inna zniknęła: liczba ta sama, zbiór inny.
    Deklaracja liczby by przepuściła i oznaczyła kopię, której user w dialogu nie widział.
    Falsyfikator: zdejmij porównanie `expected_gone_ids` w `presence.check` → `_absent == 2`."""
    con, root, vol, paths = tree
    os.remove(paths[0])
    os.remove(paths[1])
    d = presence.check(con, root, volume=vol, apply=False, confirm_under_brake=True, now=LATER)
    assert d.confirmed_gone == 2 and len(d.gone_ids) == 2
    _fits(Path(paths[0]), 1)                               # wróciła
    os.remove(paths[2])                                    # zniknęła inna
    a = presence.check(con, root, volume=vol, apply=True, force=d.confirmed_gone,
                       expected_gone_ids=d.gone_ids, now=LATER)
    assert a.confirmed_gone == 2 and a.aborted is not None and "zbiór" in a.aborted
    assert a.vanished == 0 and _absent(con) == 0 and _vanished_events(con) == 0


def test_ten_sam_zbior_zapisuje(tree, niski_prog):
    con, root, vol, paths = tree
    os.remove(paths[0])
    os.remove(paths[1])
    d = presence.check(con, root, volume=vol, apply=False, confirm_under_brake=True, now=LATER)
    a = presence.check(con, root, volume=vol, apply=True, force=d.confirmed_gone,
                       expected_gone_ids=tuple(reversed(d.gone_ids)), now=LATER)
    assert a.aborted is None and a.vanished == 2 and _absent(con) == 2


def test_deklaracja_zbioru_przy_pustym_drzewie_aborciuje_bez_stat(tree, niski_prog, monkeypatch):
    """Udział zamontowany pusty między DRY (hamulec progowy) a kliknięciem: deklaracja zbioru nie
    pochodzi z takiego stanu, więc abort od razu, bez pętli `stat` po każdym wierszu zakresu.
    Falsyfikator: zdejmij `bez_furtki` → `path_gone` wołane 4 razy, abort dopiero na zbiorze."""
    con, root, vol, paths = tree
    os.remove(paths[0])
    os.remove(paths[1])
    d = presence.check(con, root, volume=vol, apply=False, confirm_under_brake=True, now=LATER)
    for p in paths[2:]:
        os.remove(p)
    wolania = []
    prawdziwa = presence.path_gone
    monkeypatch.setattr(presence, "path_gone", lambda p: wolania.append(p) or prawdziwa(p))
    a = presence.check(con, root, volume=vol, apply=True, force=d.confirmed_gone,
                       expected_gone_ids=d.gone_ids, now=LATER)
    assert a.aborted is not None and "drzewo puste" in a.aborted
    assert wolania == [] and a.confirmed is False and _absent(con) == 0


def test_cli_force_bez_odcisku_przy_pustym_drzewie_dalej_zapisuje(tree):
    """Kontrakt CLI bez zmian: `--force N` bez odcisku zbioru przy „drzewo puste” to legalne
    sprzątanie całej sesji (deklaracja liczby, rozjazd = abort)."""
    con, root, vol, paths = tree
    for p in paths:
        os.remove(p)
    a = presence.check(con, root, volume=vol, apply=True, force=4, now=LATER)
    assert a.aborted is None and a.vanished == 4 and _absent(con) == 4
