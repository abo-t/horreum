"""Testy modułu „Nazwy z faktów" — rdzeń `horreum.naming` (Qt-wolny) + klinga `horreum.writeback`
(rename na PRAWDZIWYCH plikach) + `repo.relocate_location`.

Pokrycie: ekstraktory daty (header/filename, Z/ułamek/data-only, granice regexu), `resolve_dt`
(polityka wsadu + fallback), `compose_name` (kind-aware, dyskryminator sha1, brak daty→problem),
`run_rename` (multi-location/brak-kopii/nazwa-bez-zmian/kolizja-wsadu), pełny cykl stagingu→commit→
undo z realnym `os.rename`, ANTY-CLOBBER (dysk + baza, R3 #1/#3) i test BEHAWIORALNY kolizji (R3-P2 #7:
commit na istniejący cel → blocked, cel NIETKNIĘTY)."""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pytest
from astropy.io import fits

from horreum import db, naming, repo, scan, writeback

NOW = "2026-07-04T00:00:00+00:00"


# ============================================================ ekstraktory daty (§2)

def test_header_dt_iso_warianty():
    assert naming.header_dt("2024-03-15T21:30:45") == datetime(2024, 3, 15, 21, 30, 45)
    assert naming.header_dt("2024-03-15 21:30:45") == datetime(2024, 3, 15, 21, 30, 45)  # spacja
    assert naming.header_dt("2024-03-15T21:30:45.123Z") == datetime(2024, 3, 15, 21, 30, 45)  # Z+ułamek
    assert naming.header_dt("2024-03-15T21:30:45.9999") == datetime(2024, 3, 15, 21, 30, 45)


def test_header_dt_data_only_nie_polnoc():
    """R3 #10: data-only → None (zgłoszone jako brak czasu), NIGDY cicha północ."""
    assert naming.header_dt("2024-03-15") is None
    assert naming.header_dt("") is None
    assert naming.header_dt(None) is None
    assert naming.header_dt("śmieć") is None
    assert naming.header_dt("2024-13-40T99:99:99") is None  # nieprawidłowa data → None


def test_filename_dt_oba_wzorce():
    assert naming.filename_dt("Light_2024-03-15_21-30-45_Ha.fits") == datetime(2024, 3, 15, 21, 30, 45)
    assert naming.filename_dt("20240315_213045_M42.fits") == datetime(2024, 3, 15, 21, 30, 45)
    assert naming.filename_dt("brak_czasu.fits") is None


def test_filename_dt_granica_nie_lapie_dluzszej_liczby():
    """Granica `(?<!\\d)`/`(?!\\d)` broni przed startem w środku dłuższej liczby (fałszywy regex)."""
    assert naming.filename_dt("x20240315_213045.fits") == datetime(2024, 3, 15, 21, 30, 45)  # 'x' ok
    assert naming.filename_dt("1220240315_213045.fits") is None   # poprzedza cyfra → brak


def test_resolve_dt_polityka_i_offset():
    hdt, fdt = datetime(2024, 3, 15, 23, 0, 0), datetime(2024, 3, 15, 21, 0, 0)
    assert naming.resolve_dt(hdt, fdt, source="date_obs", offset_hours=0) == (hdt, None)
    assert naming.resolve_dt(hdt, fdt, source="filename", offset_hours=0) == (fdt, None)
    # offset pełno-godzinny (prawomocny czas innego stanowiska, NIE flaga)
    shifted, prob = naming.resolve_dt(hdt, fdt, source="date_obs", offset_hours=-2)
    assert shifted == datetime(2024, 3, 15, 21, 0, 0) and prob is None
    # brak wybranego źródła → problem
    dt, prob = naming.resolve_dt(None, fdt, source="date_obs", offset_hours=0)
    assert dt is None and "brak źródła" in prob


# ============================================================ compose_name (§1)

DT = datetime(2024, 3, 15, 21, 30, 45)
SHA = "abc123def456789000"


def test_compose_light_pelna_nazwa():
    facts = {"kind": "light", "object_canon": "NGC7000", "object_raw": "North America",
             "filter_canon": "Ha", "exptime": 300.0, "sha1_data": SHA, "ext": ".fits"}
    name, prob = naming.compose_name(facts, DT)
    assert prob is None
    assert name == "20240315_213045_NGC7000_light_Ha_300s_abc123def456.fits"


def test_compose_kalibracja_pomija_obiekt():
    """KIND-AWARE: kalibracja ma object_id=NULL z definicji → token obiektu POMINIĘTY (nie problem)."""
    facts = {"kind": "flat", "object_canon": None, "object_raw": "Flat",
             "filter_canon": "Ha", "exptime": 3.0, "sha1_data": SHA, "ext": ".fits"}
    name, prob = naming.compose_name(facts, DT)
    assert prob is None
    assert name == "20240315_213045_flat_Ha_3s_abc123def456.fits"


def test_compose_light_nierozwiazany_obiekt_unset():
    facts = {"kind": "light", "object_canon": None, "object_raw": None,
             "filter_canon": None, "exptime": None, "sha1_data": SHA, "ext": ".xisf"}
    name, prob = naming.compose_name(facts, DT)
    assert prob is None
    assert name == "20240315_213045__UNSET_light_abc123def456.xisf"   # filtr/exp pominięte


def test_compose_brak_daty_problem():
    facts = {"kind": "light", "sha1_data": SHA, "ext": ".fits"}
    name, prob = naming.compose_name(facts, None)
    assert name is None and "daty" in prob


def test_compose_sanityzacja_spacji():
    facts = {"kind": "light", "object_canon": "Heart of the Soul",
             "sha1_data": SHA, "ext": ".fits"}
    name, _ = naming.compose_name(facts, DT)
    assert " " not in name and "Heart_of_the_Soul" in name


# ============================================================ run_rename (§3) — fake targets_fn

def _row(**kw):
    base = {"frame_id": 1, "filetype": "fits", "kind": "light", "filter_canon": "Ha",
            "sha1_data": SHA, "object_canon": "NGC7000", "object_raw": None,
            "date_obs": "2024-03-15T21:30:45", "exptime": 300.0,
            "location_id": 10, "path": r"R:\A\old.fits", "mtime": "111"}
    base.update(kw)
    return base


def _targets(rows):
    by = {}
    for r in rows:
        by.setdefault(r["frame_id"], []).append(r)
    return lambda ids: [r for i in ids for r in by.get(i, [])]


def test_run_rename_podglad_ok():
    run = naming.run_rename([1], targets_fn=_targets([_row()]), source="date_obs", offset_hours=0)
    assert not run.skipped and len(run.touched) == 1
    p = run.touched[0]
    assert p.new_path == r"R:\A\20240315_213045_NGC7000_light_Ha_300s_abc123def456.fits"
    assert p.old_path == r"R:\A\old.fits" and p.mtime == "111"


def test_run_rename_multi_location_skip():
    rows = [_row(location_id=10), _row(location_id=11, path=r"R:\B\old.fits")]
    run = naming.run_rename([1], targets_fn=_targets(rows), source="date_obs", offset_hours=0)
    assert not run.touched and "multi-location" in run.skipped[0].reason


def test_run_rename_brak_kopii_skip():
    run = naming.run_rename([1], targets_fn=_targets([_row(location_id=None, path=None)]),
                            source="date_obs", offset_hours=0)
    assert not run.touched and "brak obecnej kopii" in run.skipped[0].reason


def test_run_rename_nazwa_bez_zmian_skip():
    tgt = _row(path=r"R:\A\20240315_213045_NGC7000_light_Ha_300s_abc123def456.fits")
    run = naming.run_rename([1], targets_fn=_targets([tgt]), source="date_obs", offset_hours=0)
    assert not run.touched and run.skipped[0].reason == "nazwa bez zmian"


def test_run_rename_kolizja_wsadu_skip():
    """Dwa różne frame'y → ten sam new_path (sha1 zduplikowany w danych wejściowych) → oba skip (R3 #4)."""
    rows = [_row(frame_id=1, location_id=10, path=r"R:\A\a.fits"),
            _row(frame_id=2, location_id=11, path=r"R:\A\b.fits")]
    run = naming.run_rename([1, 2], targets_fn=_targets(rows), source="date_obs", offset_hours=0)
    assert not run.touched
    assert all("kolizja nazwy w wsadzie" in s.reason for s in run.skipped)


def test_run_rename_fallback_source(monkeypatch):
    """D1: brak DATE-OBS → fallback na czas z nazwy, offset 0 (R2 #6)."""
    tgt = _row(date_obs=None, path=r"R:\A\Light_2024-03-15_21-30-45.fits")
    run = naming.run_rename([1], targets_fn=_targets([tgt]), source="date_obs", offset_hours=5)
    assert len(run.touched) == 1
    # fallback użył czasu z nazwy z offsetem 0 (NIE 5) → 21:30:45
    assert "20240315_213045" in run.touched[0].new_path


def test_run_rename_oba_zrodla_puste_powod_laczny():
    """Wiz #9: oba źródła czasu puste (brak DATE-OBS I nazwa bez czasu) → powód ŁĄCZNY,
    nie mylący komunikat z próby fallbacku ('brak źródła czasu filename' opisywał drugie
    źródło, nie realny brak). Silnik nadal pomija klatkę — zmienia się tylko diagnostyka."""
    tgt = _row(date_obs=None, path=r"R:\A\bez_czasu.fits")
    run = naming.run_rename([1], targets_fn=_targets([tgt]), source="date_obs", offset_hours=0)
    assert not run.touched
    assert run.skipped[0].reason == "brak DATE-OBS ani czasu w nazwie"


def test_run_rename_bez_fallbacku_powod_pojedynczy():
    """--no-fallback: user świadomie wyłączył drugie źródło → powód zostaje przy WYBRANYM
    źródle (pojedynczy), bo łączny komunikat kłamałby o próbie, której nie było."""
    tgt = _row(date_obs=None, path=r"R:\A\bez_czasu.fits")
    run = naming.run_rename([1], targets_fn=_targets([tgt]), source="date_obs",
                            offset_hours=0, fallback=False)
    assert not run.touched
    assert "brak źródła czasu 'date_obs'" in run.skipped[0].reason


# ============================================================ v2: tokeny folder/orig, per-typ, D-I4

import os   # noqa: E402  (import lokalny sekcji v2 — ścieżki tokenów folder/orig)


def test_compose_folder_token():
    """`folder:n` = sanitowany basename katalogu n poziomów w górę; poza korzeniem → pominięty."""
    p = os.path.join("aaa", "NGC7000 night", "sub", "old.fits")
    facts = {"kind": "light", "object_canon": "NGC7000", "sha1_data": SHA, "ext": ".fits", "path": p}
    n1, _ = naming.compose_name(facts, DT, template=[{"t": "folder", "n": 1}, "disc"])
    assert n1.startswith("sub_")                                   # katalog bezpośredni
    n2, _ = naming.compose_name(facts, DT, template=[{"t": "folder", "n": 2}])
    assert n2 == "NGC7000_night.fits"                              # 2 poziomy + sanityzacja spacji
    n9, _ = naming.compose_name(facts, DT, template=[{"t": "folder", "n": 9}, "kind"])
    assert n9 == "light.fits"                                      # poza korzeniem → folder pominięty


def test_compose_orig_token():
    """`orig:regex` = fragment ze STAREJ nazwy (stem); grupa 1 gdy jest, inaczej cały match; brak→pominięty."""
    facts = {"kind": "light", "sha1_data": SHA, "ext": ".fits",
             "path": os.path.join("d", "M42_Ha_gain100.fits")}
    whole, _ = naming.compose_name(facts, DT, template=[{"t": "orig", "re": r"gain\d+"}, "kind"])
    assert whole == "gain100_light.fits"
    grp, _ = naming.compose_name(facts, DT, template=[{"t": "orig", "re": r"gain(\d+)"}])
    assert grp == "100.fits"                                       # grupa 1
    miss, _ = naming.compose_name(facts, DT, template=[{"t": "orig", "re": r"ZZZ"}, "kind"])
    assert miss == "light.fits"                                    # brak trafienia → pominięty


def test_compose_zly_regex_defensywnie_pomija():
    """Bezpośrednio `compose_name` z niepoprawnym regexem → token pominięty, BEZ crashu (walidacja
    twarda żyje w `run_rename`)."""
    facts = {"kind": "light", "sha1_data": SHA, "ext": ".fits", "path": os.path.join("d", "x.fits")}
    name, prob = naming.compose_name(facts, DT, template=[{"t": "orig", "re": "("}, "kind"])
    assert prob is None and name == "light.fits"


def test_pick_template_precedencja():
    """`_pick_template`: filetype > kind > default > DEFAULT_TEMPLATE; lista → wprost (wsteczna zgodność)."""
    t = {"fits": ["kind"], "light": ["object"], "default": ["disc"]}
    assert naming._pick_template(t, "light", "fits") == ["kind"]       # filetype wygrywa z kind
    assert naming._pick_template(t, "light", "xisf") == ["object"]     # kind
    assert naming._pick_template(t, "dark", "raw") == ["disc"]         # default
    assert naming._pick_template(["kind"], "light", "fits") == ["kind"]  # lista → wprost
    assert naming._pick_template({"raw": ["kind"]}, "light", "fits") == naming.DEFAULT_TEMPLATE


def test_run_rename_pick_per_typ():
    """Dict per typ: klatka fits dostaje wzór 'fits' (bez obiektu/disc), nie 'default'."""
    tmpl = {"fits": ["datetime", "kind"], "default": naming.DEFAULT_TEMPLATE}
    run = naming.run_rename([1], targets_fn=_targets([_row(filetype="fits")]),
                            source="date_obs", offset_hours=0, template=tmpl)
    assert len(run.touched) == 1
    assert os.path.basename(run.touched[0].new_path) == "20240315_213045_light.fits"


def test_run_rename_kolizja_bez_disc_warning():
    """D-I4: wzór BEZ `disc` + dwie klatki o tych samych faktach → kolizja → WARNING+skip
    z podpowiedzią „dodaj token disc" (kolejka: „warning przy próbie zmiany na duplikaty")."""
    rows = [_row(frame_id=1, location_id=10, path=r"R:\A\a.fits"),
            _row(frame_id=2, location_id=11, path=r"R:\A\b.fits")]
    tmpl = ["datetime", "object", "kind", "filter", "exp"]            # BEZ disc
    run = naming.run_rename([1, 2], targets_fn=_targets(rows), source="date_obs",
                            offset_hours=0, template=tmpl)
    assert not run.touched
    assert all("dodaj token disc" in s.reason for s in run.skipped)


def test_run_rename_zly_regex_valueerror():
    """Zły regex `orig` → `ValueError` PRZED przebiegiem (INFORMUJ, nie ciche pominięcie na każdej klatce)."""
    with pytest.raises(ValueError):
        naming.run_rename([1], targets_fn=_targets([_row()]), source="date_obs",
                          offset_hours=0, template=[{"t": "orig", "re": "("}])


def test_validate_template_dict_i_lista():
    """`validate_template` chodzi po dict per typ I po liście; poprawny regex nie rzuca."""
    naming.validate_template({"fits": [{"t": "orig", "re": "NGC"}], "default": ["kind"]})
    naming.validate_template([{"t": "orig", "re": r"\d+"}, "disc"])
    with pytest.raises(ValueError):
        naming.validate_template({"fits": [{"t": "orig", "re": "["}]})


# ============================================================ integracja DB — migracja + relocate

def test_migracja_0005_pending_renames(tmp_path):
    con = db.open_db(str(tmp_path / "m.db"))
    assert con.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION >= 5
    cols = {r["name"] for r in con.execute("PRAGMA table_info(pending_renames)").fetchall()}
    assert {"run_id", "location_id", "old_path", "new_path", "expected_mtime", "status"} <= cols
    con.close()


def _seed_loc(con, path, volume="V"):
    fid, _ = repo.upsert_frame(con, sha1_data="s" + str(path), kind="light", filetype="fits",
                               camera_id=None, now=NOW)
    lid, _ = repo.add_location(con, frame_id=fid, volume=volume, path=str(path), mtime="111", now=NOW)
    return fid, lid


def test_relocate_location_update_i_event(tmp_path):
    con = db.open_db(str(tmp_path / "r.db"))
    _, lid = _seed_loc(con, r"R:\A\old.fits")
    assert repo.relocate_location(con, location_id=lid, new_path=r"R:\A\new.fits", now=NOW) is True
    assert con.execute("SELECT path FROM location WHERE id=?", (lid,)).fetchone()["path"] == r"R:\A\new.fits"
    ev = con.execute("SELECT verb, actor FROM event WHERE verb='location.renamed'").fetchone()
    assert ev["verb"] == "location.renamed" and ev["actor"] == "user:local"
    # idempotencja: ta sama ścieżka → False
    assert repo.relocate_location(con, location_id=lid, new_path=r"R:\A\new.fits", now=NOW) is False
    con.close()


def test_relocate_anty_clobber_baza(tmp_path):
    """R3 #3: cel zajęty przez INNY wiersz location(volume,path) → ValueError (UNIQUE-trap)."""
    con = db.open_db(str(tmp_path / "c.db"))
    _, lid_a = _seed_loc(con, r"R:\A\a.fits")
    _seed_loc(con, r"R:\A\b.fits")
    with pytest.raises(ValueError, match="cel zajęty"):
        repo.relocate_location(con, location_id=lid_a, new_path=r"R:\A\b.fits", now=NOW)
    con.close()


# ============================================================ pełny cykl na realnych plikach (klinga)

def _write_fits(path, **cards):
    hdu = fits.PrimaryHDU(data=np.zeros((4, 4), dtype=np.int16))
    for k, v in cards.items():
        hdu.header[k] = v
    hdu.writeto(path, overwrite=True)


def _scan_in(con, path, volume="V"):
    rec = scan.scan_file(str(path))
    scan.ingest_record(con, rec, volume=volume, now=NOW, summary=scan.ScanSummary())
    return con.execute("SELECT id, sha1_data FROM frame ORDER BY id DESC LIMIT 1").fetchone()


def _preview_and_stage(con, run_id, frame_ids):
    from horreum.gui import queries
    run = naming.run_rename(frame_ids, targets_fn=lambda ids: queries.rename_frame_targets(con, ids),
                            source="date_obs", offset_hours=0, run_id=run_id)
    for p in run.touched:
        repo.stage_rename(con, run_id=run_id, location_id=p.location_id, old_path=p.old_path,
                          new_path=p.new_path, expected_mtime=p.mtime)
    return run


def test_pelny_cykl_rename_commit_undo(tmp_path):
    con = db.open_db(str(tmp_path / "h.db"))
    p = tmp_path / "raw01.fits"
    _write_fits(p, IMAGETYP="Light", OBJECT="NGC7000", FILTER="Ha",
                **{"DATE-OBS": "2024-03-15T21:30:45", "EXPTIME": 300.0})
    fr = _scan_in(con, p)
    lid = con.execute("SELECT id FROM location WHERE path=?", (str(p),)).fetchone()["id"]

    run = _preview_and_stage(con, "RN", [fr["id"]])
    assert len(run.touched) == 1
    new_path = run.touched[0].new_path

    res = writeback.commit_renames(con, "RN", now=NOW)
    assert len(res.applied) == 1 and not res.blocked and not res.failed
    # plik na dysku PRZEMIANOWANY, stary zniknął
    import os
    assert os.path.exists(new_path) and not os.path.exists(str(p))
    # DB: location.path zaktualizowany IN-PLACE (ta sama location, tożsamość frame przeżywa)
    loc = con.execute("SELECT path, frame_id FROM location WHERE id=?", (lid,)).fetchone()
    assert loc["path"] == new_path and loc["frame_id"] == fr["id"]
    fr2 = con.execute("SELECT sha1_data FROM frame WHERE id=?", (fr["id"],)).fetchone()
    assert fr2["sha1_data"] == fr["sha1_data"]
    assert con.execute("SELECT 1 FROM event WHERE verb='location.renamed'").fetchone()

    # UNDO przywraca oryginalną nazwę
    ur = writeback.undo_renames(con, "RN", now=NOW)
    assert len(ur.restored) == 1 and not ur.blocked
    assert os.path.exists(str(p)) and not os.path.exists(new_path)
    assert con.execute("SELECT path FROM location WHERE id=?", (lid,)).fetchone()["path"] == str(p)
    con.close()


def test_commit_blocked_na_istniejacy_cel_nietkniety(tmp_path):
    """R3-P2 #7 BEHAWIORALNIE: commit renamu, gdy cel JUŻ istnieje na dysku (plik spoza bazy) →
    'blocked', a plik-cel NIETKNIĘTY. Meta-test AST nie odróżni os.replace/os.rename — chroni to zachowanie."""
    con = db.open_db(str(tmp_path / "b.db"))
    src = tmp_path / "raw02.fits"
    _write_fits(src, IMAGETYP="Light", OBJECT="M42", FILTER="OIII",
                **{"DATE-OBS": "2024-03-15T22:00:00", "EXPTIME": 120.0})
    fr = _scan_in(con, src)
    lid = con.execute("SELECT id FROM location WHERE path=?", (str(src),)).fetchone()["id"]

    run = naming.run_rename([fr["id"]], targets_fn=lambda ids: _qtargets(con, ids),
                            source="date_obs", offset_hours=0, run_id="B")
    new_path = run.touched[0].new_path
    # utwórz OBCY plik dokładnie pod celem (z innymi bajtami)
    with open(new_path, "wb") as f:
        f.write(b"OBCY-PLIK-NIE-RUSZAC")
    repo.stage_rename(con, run_id="B", location_id=lid, old_path=str(src), new_path=new_path,
                      expected_mtime=run.touched[0].mtime)

    res = writeback.commit_renames(con, "B", now=NOW)
    assert not res.applied and len(res.blocked) == 1
    import os
    assert os.path.exists(str(src))                       # źródło nietknięte
    with open(new_path, "rb") as f:
        assert f.read() == b"OBCY-PLIK-NIE-RUSZAC"        # cel NIETKNIĘTY (nie nadpisany)
    # DB niezmieniona
    assert con.execute("SELECT path FROM location WHERE id=?", (lid,)).fetchone()["path"] == str(src)
    con.close()


def _qtargets(con, ids):
    from horreum.gui import queries
    return queries.rename_frame_targets(con, ids)


# ============================================================ meta-test klingi zielony

def test_meta_test_klingi_przepuszcza_naming_i_rename():
    """naming.py NIE mutuje plików (silnik podglądu); rename żyje w writeback.py (DOOR). Import
    meta-testu i uruchomienie — offenders puste."""
    import test_writeback_safety as wbs
    wbs.test_mutacja_plikow_tylko_w_writeback()          # rzuci, gdyby naming.py był offenderem


# ============================================================ AR-29: trwały zamiar, kompensacja, rekoncyliacja
# Awaria wstrzykiwana w każde okno między `os.rename` a utrwaleniem bazy. Niezmiennik po każdym
# scenariuszu (i po ponowieniu/cofnięciu): plik istnieje dokładnie pod jedną nazwą pary, `location.path`
# lokacji wskazuje tę nazwę, lokacja ta sama (zero nowych), `location.renamed` liczy realne ruchy.

import os
import sqlite3


def _jeden_plik(tmp_path, nazwa="raw10.fits", obj="NGC7000"):
    """Baza + jeden przeskanowany FITS + staging przebiegu 'R'. Zwraca (con, lid, stara, nowa)."""
    con = db.open_db(str(tmp_path / "z.db"))
    p = tmp_path / nazwa
    _write_fits(p, IMAGETYP="Light", OBJECT=obj, FILTER="Ha",
                **{"DATE-OBS": "2024-03-15T21:30:45", "EXPTIME": 300.0})
    fr = _scan_in(con, p)
    lid = con.execute("SELECT id FROM location WHERE path=?", (str(p),)).fetchone()["id"]
    run = _preview_and_stage(con, "R", [fr["id"]])
    return con, lid, str(p), run.touched[0].new_path


def _stan(con, lid):
    loc = con.execute("SELECT path FROM location WHERE id=?", (lid,)).fetchone()["path"]
    n_loc = con.execute("SELECT count(*) FROM location").fetchone()[0]
    n_ev = con.execute("SELECT count(*) FROM event WHERE verb='location.renamed'").fetchone()[0]
    return loc, n_loc, n_ev


def _wiersz(con, run_id="R"):
    (r,) = writeback.renames_for_run(con, run_id)
    return r


def _pad_raz(monkeypatch, cel, nazwa, wyjatek):
    """Podmień `cel.nazwa` tak, by PIERWSZE wywołanie rzuciło `wyjatek`, kolejne szły do oryginału."""
    prawdziwa = getattr(cel, nazwa)
    stan = {"raz": True}

    def _f(*a, **kw):
        if stan["raz"]:
            stan["raz"] = False
            raise wyjatek
        return prawdziwa(*a, **kw)
    monkeypatch.setattr(cel, nazwa, _f)


def _bez_kompensacji(monkeypatch):
    """Kompensacja `new→old` nie wychodzi (udział zajęty) - druga próba prymitywu w tym samym wierszu."""
    prawdziwy = writeback.rename_file
    licznik = {"n": 0}

    def _f(src, dst):
        licznik["n"] += 1
        if licznik["n"] == 2:
            return writeback.RenameFileResult("failed", "PermissionError: udział zajęty")
        return prawdziwy(src, dst)
    monkeypatch.setattr(writeback, "rename_file", _f)


def test_migracja_0029_kolumna_zamiaru(tmp_path):
    con, lid, stara, nowa = _jeden_plik(tmp_path)
    assert _wiersz(con)["in_flight"] is None                       # staging nie otwiera zamiaru
    with pytest.raises(sqlite3.IntegrityError):                    # CHECK słownika kierunków
        con.execute("UPDATE pending_renames SET in_flight='w-bok'")
    con.rollback()
    con.close()


def test_zamiar_zatwierdzony_przed_os_rename_i_gasniety_z_relokacja(tmp_path, monkeypatch):
    """W chwili `os.rename` zamiar 'commit' jest już ZATWIERDZONY (widzi go drugie połączenie),
    a po sukcesie gaśnie razem ze statusem 'applied' w transakcji relokacji."""
    con, lid, stara, nowa = _jeden_plik(tmp_path)
    obserwator = sqlite3.connect(str(tmp_path / "z.db"))
    widziane = []
    prawdziwy = writeback.rename_file

    def _podglad(src, dst):
        widziane.append(obserwator.execute("SELECT in_flight, status FROM pending_renames").fetchone())
        return prawdziwy(src, dst)
    monkeypatch.setattr(writeback, "rename_file", _podglad)
    res = writeback.commit_renames(con, "R", now=NOW)
    obserwator.close()
    assert len(res.applied) == 1 and widziane == [("commit", "pending")]
    r = _wiersz(con)
    assert (r["status"], r["in_flight"]) == ("applied", None)
    assert _stan(con, lid) == (nowa, 1, 1)
    con.close()


def test_awaria_miedzy_os_rename_a_update_kompensuje(tmp_path, monkeypatch):
    """UPDATE `location.path` padł po udanym `os.rename`: kompensacja `new→old` - plik wraca, baza
    stoi pod starą nazwą, zamiar zgaszony, zero `location.renamed`. Ponowienie (nowy staging) przechodzi."""
    con, lid, stara, nowa = _jeden_plik(tmp_path)
    _pad_raz(monkeypatch, repo, "_apply_relocation", sqlite3.OperationalError("disk I/O error"))
    res = writeback.commit_renames(con, "R", now=NOW)
    assert len(res.failed) == 1 and "wrócił" in res.failed[0].reason
    assert os.path.exists(stara) and not os.path.exists(nowa)
    r = _wiersz(con)
    assert (r["status"], r["in_flight"]) == ("failed", None)
    assert _stan(con, lid) == (stara, 1, 0)
    _preview_and_stage(con, "R2", [con.execute("SELECT frame_id FROM location WHERE id=?",
                                               (lid,)).fetchone()[0]])
    assert len(writeback.commit_renames(con, "R2", now=NOW).applied) == 1
    assert _stan(con, lid) == (nowa, 1, 1) and os.path.exists(nowa)
    con.close()


def test_rozdarcie_bez_kompensacji_ponowienie_przepina_te_sama_lokacje(tmp_path, monkeypatch):
    """UPDATE padł, a kompensacja też nie wyszła: plik pod nową nazwą, baza pod starą, zamiar
    'commit' OTWARTY ('torn'). Następne wejście do commitu rekoncyliuje: TA SAMA lokacja przepięta
    na nową nazwę z `location.renamed` (ciągłość historii), status 'applied' - a cofnięcie obejmuje
    ją jak każdy rename."""
    con, lid, stara, nowa = _jeden_plik(tmp_path)
    _pad_raz(monkeypatch, repo, "_apply_relocation", sqlite3.OperationalError("disk I/O error"))
    _bez_kompensacji(monkeypatch)
    res = writeback.commit_renames(con, "R", now=NOW)
    assert len(res.failed) == 1 and "PRZENIESIONY" in res.failed[0].reason
    assert res.failed[0].path == nowa                     # wynik wskazuje, gdzie plik STOI
    assert os.path.exists(nowa) and not os.path.exists(stara)
    r = _wiersz(con)
    assert (r["status"], r["in_flight"]) == ("failed", "commit")
    assert _stan(con, lid) == (stara, 1, 0)
    monkeypatch.undo()

    ponowienie = writeback.commit_renames(con, "INNY", now=NOW)   # wejście do etapu, inny przebieg
    assert [f.status for f in ponowienie.reconciled] == ["reconciled"]
    r = _wiersz(con)
    assert (r["status"], r["in_flight"]) == ("applied", None)
    assert _stan(con, lid) == (nowa, 1, 1)
    ev = con.execute("SELECT payload, reason FROM event WHERE verb='location.renamed'").fetchone()
    assert '"pending_rename"' in ev["payload"] and "rekoncyliacja" in ev["reason"]

    ur = writeback.undo_renames(con, "R", now=NOW)
    assert len(ur.restored) == 1 and os.path.exists(stara) and not os.path.exists(nowa)
    assert _stan(con, lid) == (stara, 1, 2)
    con.close()


def test_rozdarcie_cofniecie_od_razu_obejmuje_przerwany_commit(tmp_path, monkeypatch):
    """Po rozdarciu commitu człowiek woła od razu „Cofnij": rekoncyliacja na wejściu cofnięcia robi
    z wiersza 'applied', więc cofnięcie wraca plik pod starą nazwę - zero ręcznego skanu."""
    con, lid, stara, nowa = _jeden_plik(tmp_path)
    _pad_raz(monkeypatch, repo, "_apply_relocation", sqlite3.OperationalError("disk I/O error"))
    _bez_kompensacji(monkeypatch)
    writeback.commit_renames(con, "R", now=NOW)
    monkeypatch.undo()
    ur = writeback.undo_renames(con, "R", now=NOW)
    assert len(ur.reconciled) == 1 and len(ur.restored) == 1 and not ur.failed
    assert os.path.exists(stara) and not os.path.exists(nowa)
    r = _wiersz(con)
    assert (r["status"], r["in_flight"]) == ("skipped", None)
    assert _stan(con, lid) == (stara, 1, 2)                   # przepięcie rekoncyliacji + cofnięcie
    con.close()


def test_smierc_procesu_po_os_rename_zamiar_przezywa(tmp_path, monkeypatch):
    """Proces ginie między `os.rename` a UPDATE (BaseException - kompensacji nie ma komu zrobić):
    transakcja straży wycofana, zamiar zatwierdzony wcześniej ZOSTAJE. Nowe połączenie (restart)
    rekoncyliuje: ta sama lokacja pod nową nazwą, status 'applied'."""
    con, lid, stara, nowa = _jeden_plik(tmp_path)
    _pad_raz(monkeypatch, repo, "_apply_relocation", KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        writeback.commit_renames(con, "R", now=NOW)
    con.close()
    monkeypatch.undo()
    con = db.open_db(str(tmp_path / "z.db"))
    assert os.path.exists(nowa) and not os.path.exists(stara)
    r = _wiersz(con)
    assert (r["status"], r["in_flight"]) == ("pending", "commit")
    assert _stan(con, lid) == (stara, 1, 0)
    wynik = writeback.reconcile_renames(con, now=NOW)
    assert [f.status for f in wynik] == ["reconciled"]
    assert _stan(con, lid) == (nowa, 1, 1)
    assert (_wiersz(con)["status"], _wiersz(con)["in_flight"]) == ("applied", None)
    con.close()


class _ConPadCommit(sqlite3.Connection):
    """Połączenie, którego N-te `commit()` od uzbrojenia rzuca - przed utrwaleniem albo po nim."""
    uzbrojony = 0
    po_utrwaleniu = False

    def commit(self):
        if self.uzbrojony:
            self.uzbrojony -= 1
            if self.uzbrojony == 0:
                if self.po_utrwaleniu:
                    super().commit()
                raise sqlite3.OperationalError("disk I/O error przy COMMIT")
        super().commit()


def _con_pad_commit(tmp_path):
    con = sqlite3.connect(str(tmp_path / "z.db"), factory=_ConPadCommit)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA busy_timeout = 5000")
    return con


@pytest.mark.parametrize("po_utrwaleniu", [False, True])
def test_awaria_w_trakcie_commit_bazy(tmp_path, po_utrwaleniu):
    """COMMIT transakcji straży rzuca. Nieutrwalony → kompensacja (plik wraca, 'failed', zamiar
    zgaszony). Utrwalony mimo wyjątku → baza ZGODNA z dyskiem, więc kompensacji NIE ma (cofnięcie
    pliku rozdarłoby stan spójny) - wynik 'applied'."""
    con0, lid, stara, nowa = _jeden_plik(tmp_path)
    con0.close()
    con = _con_pad_commit(tmp_path)
    con.uzbrojony, con.po_utrwaleniu = 2, po_utrwaleniu   # 1. commit = zamiar, 2. = straż relokacji
    res = writeback.commit_renames(con, "R", now=NOW)
    r = _wiersz(con)
    if po_utrwaleniu:
        assert len(res.applied) == 1 and not res.failed
        assert os.path.exists(nowa) and not os.path.exists(stara)
        assert (r["status"], r["in_flight"]) == ("applied", None)
        assert _stan(con, lid) == (nowa, 1, 1)
    else:
        assert len(res.failed) == 1 and "wrócił" in res.failed[0].reason
        assert os.path.exists(stara) and not os.path.exists(nowa)
        assert (r["status"], r["in_flight"]) == ("failed", None)
        assert _stan(con, lid) == (stara, 1, 0)
    con.close()


def test_awaria_set_rename_status_nie_zostawia_pending(tmp_path, monkeypatch):
    """AR-29 (2): status 'applied' idzie w transakcji relokacji, nie osobnym zapisem - padający
    `set_rename_status` nie zostawia wiersza 'pending' przy przeniesionym pliku i bazie."""
    con, lid, stara, nowa = _jeden_plik(tmp_path)

    def _pad(*a, **kw):
        raise sqlite3.OperationalError("disk I/O error")
    monkeypatch.setattr(repo, "set_rename_status", _pad)
    res = writeback.commit_renames(con, "R", now=NOW)
    assert len(res.applied) == 1
    assert _wiersz(con)["status"] == "applied"
    assert _stan(con, lid) == (nowa, 1, 1)
    con.close()


def test_awaria_zapisu_statusu_w_transakcji_relokacji_kompensuje(tmp_path, monkeypatch):
    """Zapis statusu wiersza (wewnątrz transakcji straży) padł: rollback obejmuje też przepięcie,
    więc kompensacja wraca plik - nigdy 'pending' przy przeniesionym pliku. Ponowienie undo/commit
    widzi stan spójny."""
    con, lid, stara, nowa = _jeden_plik(tmp_path)
    _pad_raz(monkeypatch, repo, "_zamknij_wiersz_renamu", sqlite3.OperationalError("disk I/O error"))
    res = writeback.commit_renames(con, "R", now=NOW)
    assert len(res.failed) == 1 and os.path.exists(stara) and not os.path.exists(nowa)
    assert (_wiersz(con)["status"], _wiersz(con)["in_flight"]) == ("failed", None)
    assert _stan(con, lid) == (stara, 1, 0)
    con.close()


def test_awaria_cofniecia_kompensuje_i_ponowienie_domyka(tmp_path, monkeypatch):
    """Okno między `os.rename` a UPDATE w cofnięciu: plik wraca pod nazwę z commitu, wiersz zostaje
    'applied' bez zamiaru; ponowione cofnięcie przywraca starą nazwę."""
    con, lid, stara, nowa = _jeden_plik(tmp_path)
    writeback.commit_renames(con, "R", now=NOW)
    _pad_raz(monkeypatch, repo, "_apply_relocation", sqlite3.OperationalError("disk I/O error"))
    ur = writeback.undo_renames(con, "R", now=NOW)
    assert len(ur.failed) == 1 and os.path.exists(nowa) and not os.path.exists(stara)
    assert (_wiersz(con)["status"], _wiersz(con)["in_flight"]) == ("applied", None)
    ur2 = writeback.undo_renames(con, "R", now=NOW)
    assert len(ur2.restored) == 1 and os.path.exists(stara)
    assert _stan(con, lid) == (stara, 1, 2)
    con.close()


def test_rozdarcie_cofniecia_rekoncyliacja_konczy_jako_cofniete(tmp_path, monkeypatch):
    """Cofnięcie przeniosło plik pod starą nazwę, UPDATE padł, kompensacja też: zamiar 'undo'.
    Rekoncyliacja przepina lokację na starą nazwę i kończy wiersz jako 'skipped' (cofnięto)."""
    con, lid, stara, nowa = _jeden_plik(tmp_path)
    writeback.commit_renames(con, "R", now=NOW)
    _pad_raz(monkeypatch, repo, "_apply_relocation", sqlite3.OperationalError("disk I/O error"))
    _bez_kompensacji(monkeypatch)
    ur = writeback.undo_renames(con, "R", now=NOW)
    assert len(ur.failed) == 1 and ur.failed[0].path == stara and os.path.exists(stara)
    assert _wiersz(con)["in_flight"] == "undo"
    monkeypatch.undo()
    wynik = writeback.reconcile_renames(con, now=NOW)
    assert [f.status for f in wynik] == ["reconciled"]
    r = _wiersz(con)
    assert (r["status"], r["reason"], r["in_flight"]) == ("skipped", "cofnięto (undo)", None)
    assert _stan(con, lid) == (stara, 1, 2)
    con.close()


def _rozdarty(tmp_path, monkeypatch):
    con, lid, stara, nowa = _jeden_plik(tmp_path)
    _pad_raz(monkeypatch, repo, "_apply_relocation", sqlite3.OperationalError("disk I/O error"))
    _bez_kompensacji(monkeypatch)
    writeback.commit_renames(con, "R", now=NOW)
    monkeypatch.undo()
    return con, lid, stara, nowa


def test_rekoncyliacja_odmawia_przy_innym_mtime(tmp_path, monkeypatch):
    """Plik pod nową nazwą ma `mtime` inny niż kopia w bazie - to może nie być ten plik. Zamiar
    zostaje, baza nietknięta, plik nietknięty (rozmiar NIE jest dowodem tożsamości)."""
    con, lid, stara, nowa = _rozdarty(tmp_path, monkeypatch)
    st = os.stat(nowa)
    os.utime(nowa, (st.st_atime, st.st_mtime + 3600))
    (w,) = writeback.reconcile_renames(con, now=NOW)
    assert w.status == "blocked" and "mtime" in w.reason
    assert _wiersz(con)["in_flight"] == "commit"
    assert _stan(con, lid) == (stara, 1, 0) and os.path.exists(nowa)
    con.close()


def test_rekoncyliacja_odmawia_gdy_skan_wciagnal_cel(tmp_path, monkeypatch):
    """Skan zdążył wciągnąć plik spod nowej nazwy jako drugą kopię klatki: przepięcie złamałoby
    `UNIQUE(volume, path)`. Zamiar zostaje z receptą, oba wiersze lokacji i plik nietknięte."""
    con, lid, stara, nowa = _rozdarty(tmp_path, monkeypatch)
    _scan_in(con, nowa)
    (w,) = writeback.reconcile_renames(con, now=NOW)
    assert w.status == "blocked" and "skan wciągnął" in w.reason
    assert _wiersz(con)["in_flight"] == "commit"
    assert con.execute("SELECT path FROM location WHERE id=?", (lid,)).fetchone()["path"] == stara
    assert os.path.exists(nowa)
    rn = writeback.commit_renames(con, "R", now=NOW)        # wiersz z otwartym zamiarem nie ruszany
    assert not rn.applied and os.path.exists(nowa)
    con.close()


def test_blad_renamu_przy_milczacym_udziale_zostawia_zamiar(tmp_path, monkeypatch):
    """Serwer przeniósł plik, klient dostał błąd, a udział zamilkł (`_przeszedl` nie widzi pliku
    pod żadną nazwą). Brak dowodu, że plik stoi pod starą nazwą = zamiar ZOSTAJE ('torn'); gdy dysk
    wraca, rekoncyliacja przepina tę samą lokację."""
    con, lid, stara, nowa = _jeden_plik(tmp_path)
    prawdziwy = writeback.rename_file

    def _przeniosl_i_zglosil_blad(src, dst):
        prawdziwy(src, dst)
        return writeback.RenameFileResult("failed", "OSError: sieć zerwana")
    monkeypatch.setattr(writeback, "rename_file", _przeniosl_i_zglosil_blad)
    monkeypatch.setattr(writeback, "_przeszedl", lambda src, dst: False)
    res = writeback.commit_renames(con, "R", now=NOW)
    assert len(res.failed) == 1 and "zamiar renamu zostaje" in res.failed[0].reason
    assert _wiersz(con)["in_flight"] == "commit"
    monkeypatch.undo()
    (w,) = writeback.reconcile_renames(con, now=NOW)
    assert w.status == "reconciled" and _stan(con, lid) == (nowa, 1, 1)
    con.close()


def test_zamiar_zgaszony_przez_inny_proces_zatrzymuje_rename(tmp_path, monkeypatch):
    """Między zatwierdzeniem zamiaru a strażą rekoncyliacja innego procesu gasi zamiar: straż pod
    blokadą to widzi i rename się nie odbywa - plik nietknięty, baza nietknięta."""
    con, lid, stara, nowa = _jeden_plik(tmp_path)
    prawdziwy = repo.open_rename_intent

    def _otworz_i_zgas(con_, *, rename_id, direction):
        prawdziwy(con_, rename_id=rename_id, direction=direction)
        repo.drop_rename_intent(con_, rename_id=rename_id)
    monkeypatch.setattr(repo, "open_rename_intent", _otworz_i_zgas)
    res = writeback.commit_renames(con, "R", now=NOW)
    assert not res.applied and len(res.blocked) == 1 and "inny proces" in res.blocked[0].reason
    assert os.path.exists(stara) and not os.path.exists(nowa)
    assert _stan(con, lid) == (stara, 1, 0)
    con.close()


def test_rekoncyliacja_odmawia_przy_obcej_tresci_o_tym_samym_mtime(tmp_path, monkeypatch):
    """`mtime` da się przenieść kopiowaniem: obcy plik pod nową nazwą z tym samym czasem nie jest
    naszym plikiem - rozstrzyga sha1 treści z `location.file_sha1`."""
    con, lid, stara, nowa = _rozdarty(tmp_path, monkeypatch)
    st = os.stat(nowa)
    with open(nowa, "r+b") as f:
        f.seek(-1, os.SEEK_END)
        bajt = f.read(1)
        f.seek(-1, os.SEEK_END)
        f.write(bytes([bajt[0] ^ 0xFF]))
    os.utime(nowa, ns=(st.st_atime_ns, st.st_mtime_ns))
    (w,) = writeback.reconcile_renames(con, now=NOW)
    assert w.status == "blocked" and "inną treść" in w.reason
    assert _wiersz(con)["in_flight"] == "commit" and _stan(con, lid) == (stara, 1, 0)
    con.close()


def test_skan_nie_rusza_zamiarow_cudzego_woluminu_i_przezywa_awarie(tmp_path, monkeypatch):
    """Skan innego woluminu nie rozstrzyga zamiarów `R:`; wyjątek rekoncyliacji jednego zamiaru
    jest wynikiem 'blocked', a nie przerwaniem etapu."""
    con, lid, stara, nowa = _rozdarty(tmp_path, monkeypatch)
    pusty = tmp_path / "inny"
    pusty.mkdir()
    s = scan.scan_tree(con, str(pusty), volume="INNY", now=NOW)
    assert s.renames_settled == [] and _wiersz(con)["in_flight"] == "commit"

    def _pada(*a, **k):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(writeback, "_rozstrzygnij_zamiar", _pada)
    (w,) = writeback.reconcile_renames(con, now=NOW)
    assert w.status == "blocked" and "database is locked" in w.reason
    con.close()


def test_skan_rozstrzyga_zamiar_renamu_zanim_wciagnie_plik(tmp_path, monkeypatch):
    """Rozdarty rename, a człowiek puszcza zwykły skan katalogu zamiast ponowienia: skan najpierw
    rekoncyliuje zamiar (TA SAMA lokacja pod nową nazwą, `location.renamed`), więc plik spod nowej
    nazwy nie wjeżdża jako druga kopia - lokacji dalej jest jedna."""
    con, lid, stara, nowa = _rozdarty(tmp_path, monkeypatch)
    s = scan.scan_tree(con, str(tmp_path), volume="V", now=NOW)
    assert [f.status for f in s.renames_settled] == ["reconciled"]
    assert _stan(con, lid) == (nowa, 1, 1)
    assert _wiersz(con)["in_flight"] is None
    con.close()


def test_odrzucenie_stagingu_zostawia_wiersz_z_zamiarem(tmp_path, monkeypatch):
    """„Odrzuć" (`clear_renames_for_run`) nie kasuje jedynego śladu renamu bez przepięcia bazy."""
    con, lid, stara, nowa = _rozdarty(tmp_path, monkeypatch)
    repo.clear_renames_for_run(con, "R")
    assert _wiersz(con)["in_flight"] == "commit"
    con.close()
