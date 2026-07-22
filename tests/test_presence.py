"""Pass OBECNOŚCI kopii (P5, Issue #7) — kryteria akceptacji z briefu `PLAN_p5_znikniecia.md §6`.

Buduje REALNE drzewa FITS w `tmp_path` (zero dotknięcia `R:`), skanuje je pniem i sprawdza, że
zdejmowanie obecności ma DOWÓD, a każdy stan nie-będący zniknięciem trafia do własnego kubełka.

Pokrycie META (bez własnych testów tutaj — meta-testy chodzą po `rglob`, więc nowy moduł wchodzi
pod nie automatycznie): `test_repo_safety.py` pilnuje, że `presence.py` nie wykonuje DML,
`test_writeback_safety.py` — że nie mutuje plików (modul świadomie POZA `DOORS`),
`test_gui_isolation.py` — że nie importuje Qt.
"""
import inspect
import os
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits

from horreum import db, presence, repo, resolver
from horreum.gui import queries
from horreum.scan import ScanSummary, ingest_record, scan_file, scan_tree
from horreum.volumes import volume_serial

NOW = "2026-07-22T12:00:00"
LATER = "2026-07-22T18:00:00"


def _fits(path, value=0):
    """Minimalny light o UNIKALNYCH pikselach — identyczne piksele = jeden frame (`sha1_data`)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    hdu = fits.PrimaryHDU(data=np.full((4, 4), value, dtype=np.uint16))
    hdu.header["INSTRUME"] = "ZWO ASI2600MM Pro"
    hdu.header["IMAGETYP"] = "Light Frame"
    hdu.writeto(str(path))
    return path


def _count(con, verb):
    return con.execute("SELECT COUNT(*) FROM event WHERE verb = ?", (verb,)).fetchone()[0]


def _loc(con, path):
    return con.execute(
        "SELECT id, present, unreadable_since FROM location WHERE path = ?", (path,)).fetchone()


@pytest.fixture
def tree(tmp_path):
    """(con, root, volume, paths) — trzy lighty zeskanowane z realnym serialem woluminu.

    Serial jest KONFRONTOWANY przez pass (D-V-2), więc testy muszą używać prawdziwego; poza
    Windowsem `volume_serial` zwraca None i cały kontrakt passa jest nieoznaczony → skip."""
    root = tmp_path / "ASTRO"
    paths = [str(_fits(root / "LIGHTS" / f"l{i}.fits", value=i + 1)) for i in range(3)]
    vol = volume_serial(str(root))
    if vol is None:
        pytest.skip("volume_serial nieustalony (nie-Windows) — pass wymaga trwałego serialu")
    con = db.open_db(str(tmp_path / "h.db"))
    scan_tree(con, str(root), volume=vol, now=NOW)
    yield con, str(root), vol, paths
    con.close()


# ─────────────────────────────────────────────────────────── 1–2: rdzeń + idempotencja

def test_1_znikniecie_potwierdzone_zdejmuje_obecnosc(tree):
    """Skasowany plik → kandydat → potwierdzony → `present=0` + JEDEN `location.vanished`."""
    con, root, vol, paths = tree
    os.remove(paths[0])
    s = presence.check(con, root, volume=vol, apply=True, now=LATER)
    assert (s.scoped, s.walked, s.candidates, s.confirmed_gone, s.vanished) == (3, 2, 1, 1, 1)
    assert _loc(con, paths[0])["present"] == 0
    assert _loc(con, paths[1])["present"] == 1
    assert _count(con, "location.vanished") == 1


def test_2_idempotencja_drugi_przebieg_bez_eventow(tree):
    """Powtórka na tym samym stanie: zero kandydatów, zero eventów (kopia już nieobecna)."""
    con, root, vol, paths = tree
    os.remove(paths[0])
    presence.check(con, root, volume=vol, apply=True, now=LATER)
    before = _count(con, "location.vanished")
    s = presence.check(con, root, volume=vol, apply=True, now=LATER)
    assert (s.scoped, s.candidates, s.vanished) == (2, 0, 0)
    assert _count(con, "location.vanished") == before


# ─────────────────────────────────────────────────────── 3, 13, 15: co NIE jest zniknięciem

def test_3_kopia_pod_wykluczonym_drzewem_nie_jest_kandydatem(tree):
    """Plik pod `_WBPP` istnieje — jest tylko poza zasięgiem skanu → `out_of_reach`, nie kandydat."""
    con, root, vol, _paths = tree
    p = str(_fits(Path(root) / "_WBPP" / "proj.fits", value=99))
    ingest_record(con, scan_file(p), volume=vol, now=NOW, summary=ScanSummary())
    s = presence.check(con, root, volume=vol, apply=True, now=LATER)
    assert (s.out_of_reach, s.candidates, s.vanished) == (1, 0, 0)
    assert _loc(con, p)["present"] == 1


def test_13_katalog_nieprzeczytany_traktowany_jak_prune(tree, monkeypatch):
    """Poddrzewo, którego `os.walk` nie przeczytał (`errors_out`), NIE produkuje zniknięć.

    Podstawiamy `iter_headers`, bo odebranie uprawnień do katalogu jest na Windowsie testem ACL,
    nie testem passa: sprawdzamy KLASYFIKACJĘ błędu, a nie zachowanie `os.walk`."""
    con, root, vol, paths = tree
    lights = str(Path(root) / "LIGHTS")

    def fake(_root, excluded_out=None, errors_out=None):
        errors_out.append(lights)                     # cały katalog nieprzeczytany
        return []

    monkeypatch.setattr(presence, "iter_headers", fake)
    s = presence.check(con, root, volume=vol, apply=True, now=LATER)
    assert s.out_of_reach == 3 and s.candidates == 0 and s.vanished == 0
    assert _loc(con, paths[0])["present"] == 1


def test_15_granica_separatora_wbppx_nie_jest_wykluczony(tree):
    """`_WBPP` jest wykluczony, `_WBPPX` NIE — plik z `_WBPPX` znika i MUSI być kandydatem.
    Gołe `startswith` bez separatora schowałoby realne zniknięcie w `out_of_reach`."""
    con, root, vol, _paths = tree
    _fits(Path(root) / "_WBPP" / "proj.fits", value=98)        # zapełnia listę wykluczeń
    p = str(_fits(Path(root) / "_WBPPX" / "real.fits", value=97))
    scan_tree(con, root, volume=vol, now=NOW)
    assert _loc(con, p) is not None                            # _WBPPX skanowany normalnie
    os.remove(p)
    s = presence.check(con, root, volume=vol, apply=True, now=LATER)
    assert s.out_of_reach == 0 and s.confirmed_gone == 1
    assert _loc(con, p)["present"] == 0


# ──────────────────────────────────────────────────── 4, 14, 16: dowód, nie różnica zbiorów

def test_4_kandydat_ktory_jednak_istnieje_nie_jest_zapisywany(tree):
    """Dryf wielkości liter DB↔dysk: wiersz nie trafia w przejście, ale plik JEST → `resurfaced`."""
    con, root, vol, paths = tree
    upper = str(Path(paths[0]).parent / Path(paths[0]).name.upper())
    repo.relocate_location(con, location_id=_loc(con, paths[0])["id"], new_path=upper, now=NOW)
    s = presence.check(con, root, volume=vol, apply=True, now=LATER)
    assert (s.candidates, s.resurfaced, s.confirmed_gone, s.vanished) == (1, 1, 0, 0)
    assert s.resurfaced_paths == [upper]
    assert _loc(con, upper)["present"] == 1


def test_14_stat_bez_rozstrzygniecia_nie_zapisuje(tree, monkeypatch):
    """`OSError` inny niż ENOENT (brak uprawnień, zerwany SMB) → `undecided`, ZERO zapisu."""
    con, root, vol, paths = tree
    os.remove(paths[0])
    monkeypatch.setattr(presence, "path_gone", lambda _p: None)
    s = presence.check(con, root, volume=vol, apply=True, now=LATER)
    assert (s.candidates, s.undecided, s.confirmed_gone, s.vanished) == (1, 1, 0, 0)
    assert _loc(con, paths[0])["present"] == 1
    assert _count(con, "location.vanished") == 0


def test_16_dwa_wiersze_roznia_sie_tylko_wielkoscia_liter(tree):
    """Klucz różnicy zbiorów jest BINARNY: wiersz o innym casingu nie scala się z realnym i nie
    ginie po cichu (fałszywy negatyw byłby niewykrywalny)."""
    con, root, vol, paths = tree
    upper = str(Path(paths[0]).parent / Path(paths[0]).name.upper())
    frame_id = con.execute("SELECT frame_id FROM location WHERE path = ?", (paths[0],)).fetchone()[0]
    repo.add_location(con, frame_id=frame_id, volume=vol, path=upper, now=NOW)
    s = presence.check(con, root, volume=vol, apply=False, now=LATER)
    assert s.scoped == 4 and s.candidates == 1      # oba wiersze w zakresie, tylko jeden nietrafiony


# ──────────────────────────────────────────────────────── 5, 11, 12: przesłanki i hamulec

def test_5_hamulec_zatrzymuje_apply_ale_dry_raportuje(tree):
    """Puste drzewo: `--apply` aborciuje bez zapisu, DRY nadal pokazuje pełne liczniki + baner."""
    con, root, vol, paths = tree
    for p in paths:
        os.remove(p)
    a = presence.check(con, root, volume=vol, apply=True, now=LATER)
    assert a.aborted is not None and a.vanished == 0
    assert _count(con, "location.vanished") == 0
    d = presence.check(con, root, volume=vol, apply=False, now=LATER)
    # DRY nie „aborciuje" — nie miał czego zatrzymywać. Hamulec jest BANEREM, a raport pełny;
    # potwierdzeń świadomie nie liczono (to koszt, przed którym hamulec chroni).
    assert d.aborted is None and d.brake is not None
    assert d.scoped == 3 and d.candidates == 3 and d.confirmed is False


def test_5b_force_przelamuje_hamulec_ale_musi_sie_zgadzac(tree):
    """`--force N` = deklaracja intencji: zgodna przechodzi, rozjazd aborciuje BEZ zapisu."""
    con, root, vol, paths = tree
    for p in paths:
        os.remove(p)
    zly = presence.check(con, root, volume=vol, apply=True, force=2, now=LATER)
    assert zly.aborted is not None and zly.vanished == 0
    assert _count(con, "location.vanished") == 0
    ok = presence.check(con, root, volume=vol, apply=True, force=3, now=LATER)
    assert ok.vanished == 3 and ok.aborted is None
    assert _count(con, "location.vanished") == 3


def test_11_zakres_pusty_aborciuje(tree, tmp_path):
    """Zły root: 0 lokacji w zakresie MUSI być abortem, nie cichym „nic nie znikło"."""
    con, _root, vol, _paths = tree
    inny = tmp_path / "INNY"
    _fits(inny / "x.fits", value=42)
    s = presence.check(con, str(inny), volume=vol, apply=True, now=LATER)
    assert s.scoped == 0 and s.aborted is not None and "zakres pusty" in s.aborted


def test_12_rozjazd_serialu_aborciuje(tree):
    """Zamontowany wolumin ≠ zakres w bazie → abort przed jakimkolwiek odczytem drzewa."""
    con, root, _vol, paths = tree
    os.remove(paths[0])
    s = presence.check(con, root, volume="DEADBEEF", apply=True, now=LATER)
    assert s.aborted is not None and s.walked == 0 and s.vanished == 0
    assert _loc(con, paths[0])["present"] == 1


# ────────────────────────────────────────────────────────────── 6: DRY nie dotyka bazy

def test_6_dry_nie_zmienia_ani_wiersza(tree):
    con, root, vol, paths = tree
    os.remove(paths[0])
    s = presence.check(con, root, volume=vol, apply=False, now=LATER)
    assert (s.confirmed_gone, s.vanished, s.run_id) == (1, 0, None)
    assert s.gone_paths == [paths[0]]
    assert _loc(con, paths[0])["present"] == 1
    assert _count(con, "location.vanished") == 0


# ──────────────────────────────────────────── 7, 9, 17: marker × zniknięcie (D-V-5, D-V-8)

def test_7_marker_gasnie_a_stara_wartosc_zostaje_w_evencie(tree):
    """Kopia oznaczona nieczytelną znika → `present=0`, marker NULL, payload niesie starą wartość;
    kubełek `unreadable` opada BEZ zmiany predykatów w `resolver.review_state`."""
    con, root, vol, paths = tree
    loc = _loc(con, paths[0])
    sha = con.execute("SELECT f.sha1_data FROM frame f JOIN location l ON l.frame_id = f.id "
                      "WHERE l.id = ?", (loc["id"],)).fetchone()[0]
    repo.refresh_location_unreadable(con, location_id=loc["id"], sha1_data=sha, path=paths[0],
                                     mtime="2026-07-22T09:00:00", reason="I/O", now=NOW)
    assert resolver.review_state(con).unreadable == 1
    os.remove(paths[0])
    presence.check(con, root, volume=vol, apply=True, now=LATER)
    after = _loc(con, paths[0])
    assert after["present"] == 0 and after["unreadable_since"] is None
    assert resolver.review_state(con).unreadable == 0
    payload = con.execute(
        "SELECT payload FROM event WHERE verb = 'location.vanished'").fetchone()[0]
    assert NOW in payload                                  # unreadable_since_before zachowane


def test_9_inwariant_present0_implikuje_brak_markera(tree):
    """Po dowolnej sekwencji: ani jednego wiersza `present=0 AND unreadable_since IS NOT NULL`."""
    con, root, vol, paths = tree
    loc = _loc(con, paths[0])
    sha = con.execute("SELECT sha1_data FROM frame WHERE id = "
                      "(SELECT frame_id FROM location WHERE id = ?)", (loc["id"],)).fetchone()[0]
    repo.refresh_location_unreadable(con, location_id=loc["id"], sha1_data=sha, path=paths[0],
                                     mtime="2026-07-22T09:00:00", reason="I/O", now=NOW)
    os.remove(paths[0])
    presence.check(con, root, volume=vol, apply=True, now=LATER)
    scan_tree(con, root, volume=vol, now=LATER)
    assert con.execute("SELECT COUNT(*) FROM location "
                       "WHERE present = 0 AND unreadable_since IS NOT NULL").fetchone()[0] == 0


def test_17_powrot_kopii_nieczytelnej_przywraca_obecnosc(tree):
    """D-V-8: `refresh_location_unreadable` wołane jest WYŁĄCZNIE gdy plik istnieje, więc musi
    przywrócić `present=1` — inaczej powrót + transient awaria dają hybrydę zakazaną przez D-V-5."""
    con, root, vol, paths = tree
    os.remove(paths[0])
    presence.check(con, root, volume=vol, apply=True, now=LATER)
    loc = _loc(con, paths[0])
    assert loc["present"] == 0
    sha = con.execute("SELECT sha1_data FROM frame WHERE id = "
                      "(SELECT frame_id FROM location WHERE id = ?)", (loc["id"],)).fetchone()[0]
    zmieniono = repo.refresh_location_unreadable(
        con, location_id=loc["id"], sha1_data=sha, path=paths[0], mtime="2026-07-23T09:00:00",
        reason="I/O po powrocie", now=LATER)
    after = _loc(con, paths[0])
    assert zmieniono and after["present"] == 1 and after["unreadable_since"] == LATER


# ──────────────────────────────────────────────────────────── 8: zmartwychwstanie przez skan

def test_8_powrot_pliku_o_tym_samym_mtime_przywraca_obecnosc(tree):
    """Brama przyrostowa NIE pomija kopii nieobecnej — inaczej `present=0` byłoby drzwiami
    jednokierunkowymi. Powrót niesie `location.refreshed` z `{present: 0→1}`."""
    con, root, vol, paths = tree
    bajty, st = Path(paths[0]).read_bytes(), os.stat(paths[0])
    os.remove(paths[0])
    presence.check(con, root, volume=vol, apply=True, now=LATER)
    assert _loc(con, paths[0])["present"] == 0
    Path(paths[0]).write_bytes(bajty)
    os.utime(paths[0], (st.st_atime, st.st_mtime))         # TEN SAM mtime — brama by pominęła
    s = scan_tree(con, root, volume=vol, now=LATER)
    assert s.skipped == 2 and _loc(con, paths[0])["present"] == 1
    payload = con.execute(
        "SELECT payload FROM event WHERE verb = 'location.refreshed' "
        "ORDER BY id DESC LIMIT 1").fetchone()[0]
    assert '"present"' in payload


def test_8b_backstop_skanu_znikniecie_w_biegu_nie_zaklada_markera(tree, monkeypatch):
    """Plik znikający MIĘDZY listowaniem a odczytem (D-V-8) idzie do `mark_location_vanished`,
    nie do markera — inaczej powstałaby hybryda `present=0` + „do przeczytania"."""
    con, root, vol, paths = tree
    import horreum.scan as scan_mod

    def znikaj(path):                                      # scan_file pada, bo pliku już nie ma
        if path == paths[0]:
            os.remove(paths[0])
            raise OSError(2, "No such file or directory")
        return scan_file(path)

    monkeypatch.setattr(scan_mod, "scan_file", znikaj)
    st = os.stat(paths[0])
    os.utime(paths[0], (st.st_atime, st.st_mtime + 100))    # brama musi PUŚCIĆ plik do odczytu
    s = scan_tree(con, root, volume=vol, now=LATER)
    after = _loc(con, paths[0])
    assert s.vanished == 1 and after["present"] == 0 and after["unreadable_since"] is None


# ──────────────────────────────────────────────────────── 18, 19: dryf i multi-location

def test_18_dryf_sciezki_miedzy_planem_a_zapisem_pomija_wiersz(tree):
    """Kotwica anty-stale: rename z GUI między planem a zapisem → `False`, ZERO zapisu (wiersz
    wskazuje wtedy na ISTNIEJĄCY plik)."""
    con, root, vol, paths = tree
    loc_id = _loc(con, paths[0])["id"]
    repo.relocate_location(con, location_id=loc_id, new_path=paths[0] + ".nowy", now=NOW)
    zapisano = repo.mark_location_vanished(
        con, location_id=loc_id, expected_path=paths[0], root=root, run_id="r1", now=LATER)
    assert zapisano is False
    assert _count(con, "location.vanished") == 0
    assert _loc(con, paths[0] + ".nowy")["present"] == 1


def test_19_multilocation_znika_jedna_z_dwoch_kopii(tree, tmp_path):
    """Klatka z dwiema kopiami: zniknięcie jednej NIE czyni jej „zniknioną" (`vanished_frames`
    wymaga braku WSZYSTKICH), a przestaje być duplikatem (`dup_frame_ids` liczy obecne)."""
    con, root, vol, paths = tree
    kopia = str(Path(root) / "LIGHTS" / "kopia.fits")
    Path(kopia).write_bytes(Path(paths[0]).read_bytes())   # te same piksele = TEN SAM frame
    scan_tree(con, root, volume=vol, now=NOW)
    frame_id = con.execute("SELECT frame_id FROM location WHERE path = ?", (kopia,)).fetchone()[0]
    assert frame_id in queries.dup_frame_ids(con)
    os.remove(kopia)
    presence.check(con, root, volume=vol, apply=True, now=LATER)
    assert frame_id not in queries.dup_frame_ids(con)      # już nie duplikat — poprawnie
    assert queries.tasks_state(con)["vanished_frames"] == 0   # druga kopia żyje


# ────────────────────────────────────────────────────────── CLI: kod wyjścia = WERDYKT

def test_cli_dry_zwraca_werdykt_a_abort_kod_1(tree, capsys):
    """Kod wyjścia mówi o WERDYKCIE, nie o zapisie: przebieg, który pominął potwierdzenia albo
    padł na przesłance, MUSI dać 1 — inaczej skrypt myli „nic nie znikło" z „nie sprawdziłem"."""
    from horreum import cli
    con, root, vol, paths = tree
    con.commit()
    dbp = con.execute("PRAGMA database_list").fetchone()[2]
    os.remove(paths[0])
    assert cli.main(["presence", dbp, "--root", root, "--volume", vol]) == 0
    assert "potwierdzone znikniecia: 1" in capsys.readouterr().out
    assert cli.main(["presence", dbp, "--root", root, "--volume", "DEADBEEF"]) == 1
    assert "ABORT" in capsys.readouterr().out


# ───────────────────────────────────────────────────────────────── 20: SPOT strukturalny

def test_20_location_facts_pokrywaja_literal_update():
    """Każda nazwa z `_LOCATION_FACTS` MUSI występować w literale UPDATE `refresh_location` —
    inaczej diff wykrywa zmianę, której UPDATE nie zapisuje, i event leci co skan w nieskończoność."""
    src = inspect.getsource(repo.refresh_location)
    for name in repo._LOCATION_FACTS:
        assert f"{name} = ?" in src, f"{name} w _LOCATION_FACTS, ale nie w UPDATE"
