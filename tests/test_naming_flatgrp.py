"""Testy tokenów wzoru nazwy: `flatgrp` (grupa flatu z nazwy mastera podpiętego w `calibration`),
`trail` (końcowy separator `_` przed rozszerzeniem) i parametr `case` tokenu `kind`.

Pokrycie: rdzeń `compose_name` (wartość, brak flatu → znacznik NOFLAT, grupa nieczytelna → problem,
kind-aware), walidacja wzoru (trail nie na końcu, nieznany case), wsteczna zgodność gołego `kind`,
`run_rename` z problemem flatu → skip z powodem, oraz `queries.rename_frame_targets` na prawdziwej
bazie: ogniwo flatu podzapytaniem (wiele kopii mastera NIE mnoży wierszy lighta)."""

from __future__ import annotations

import os
from datetime import datetime

import pytest

from horreum import db, naming, repo
from horreum.gui import queries

NOW = "2026-10-04T00:00:00+00:00"
DT = datetime(2026, 8, 8, 21, 58, 45)
SHA = "abc123def456789000"
MASTER = r"R:\ASTRO_\CALIBRATION\masters\flats\A140R_2600MM\OIII\MASTERFLAT_FLATGRP_202511010_FILTER_OIII_.xisf"
WZOR_SIOSTR = ["object", "datetime", {"t": "kind", "case": "upper"}, "filter", "exp", "flatgrp", "trail"]


def _facts(**kw):
    base = {"kind": "light", "object_canon": "CTB1", "object_raw": "CTB 1", "filter_canon": "OIII",
            "exptime": 300.0, "sha1_data": SHA, "ext": ".fits", "path": r"R:\A\CTB 1_LIGHT_O_300.00s_0000.fits",
            "flat_master_id": 7, "flat_paths": [MASTER]}
    base.update(kw)
    return base


# ============================================================ compose_name

def test_wzor_siostr_daje_konwencje_archiwum():
    """Pełny wzór konwencji sióstr: grupa z nazwy mastera, LIGHT wielkimi, `_` przed rozszerzeniem."""
    name, prob = naming.compose_name(_facts(), DT, template=WZOR_SIOSTR)
    assert prob is None
    assert name == "CTB1_20260808_215845_LIGHT_OIII_300s_FLATGRP_202511010_.fits"


def test_flatgrp_brak_flatu_znacznik_noflat():
    """Light bez ogniwa flatu → `FLATGRP_NOFLAT` (znacznik konwencji archiwum), nie dziura."""
    name, prob = naming.compose_name(_facts(flat_master_id=None, flat_paths=[]), DT,
                                     template=["kind", "flatgrp"])
    assert prob is None and name == "light_FLATGRP_NOFLAT.fits"


def test_flatgrp_master_bez_kopii_problem():
    """Flat podpięty, master bez obecnej kopii → problem (klatka pominięta), nigdy pusty segment."""
    name, prob = naming.compose_name(_facts(flat_paths=[]), DT, template=["kind", "flatgrp"])
    assert name is None and "bez obecnej kopii" in prob


def test_flatgrp_nazwa_mastera_bez_tokenu_problem():
    name, prob = naming.compose_name(_facts(flat_paths=[r"R:\M\MasterFlat_OIII.xisf"]), DT,
                                     template=["kind", "flatgrp"])
    assert name is None and "brak FLATGRP" in prob and "MasterFlat_OIII.xisf" in prob


def test_flatgrp_pusta_grupa_po_sanityzacji_problem():
    """Grupa złożona z samych znaków niedozwolonych znika w sanityzacji - to problem z powodem, nie
    nazwa z segmentem `FLATGRP_` bez wartości."""
    seg, problem = naming._flatgrp_segment(
        {"flat_master_id": 9, "flat_paths": ["/m/MASTERFLAT_FLATGRP_<>_FILTER_OIII.xisf"]})
    assert seg is None and "pusta grupa" in problem


def test_flatgrp_kopie_o_roznych_grupach_problem():
    inna = MASTER.replace("202511010", "202510180")
    name, prob = naming.compose_name(_facts(flat_paths=[MASTER, inna]), DT, template=["flatgrp"])
    assert name is None and "202510180" in prob and "202511010" in prob


def test_flatgrp_dwie_kopie_tej_samej_grupy_ok():
    kopia = MASTER.replace(r"R:\ASTRO_", r"F:\backup")
    name, prob = naming.compose_name(_facts(flat_paths=[MASTER, kopia]), DT, template=["flatgrp"])
    assert prob is None and name == "FLATGRP_202511010.fits"


def test_flatgrp_pominiety_poza_lightem():
    """Kind-aware: ogniwo flatu ma wyłącznie `light`; kalibracja i master_light → token pominięty."""
    for kind in ("master_flat", "dark", "master_light"):
        name, prob = naming.compose_name(_facts(kind=kind, flat_master_id=None, flat_paths=[]), DT,
                                         template=["kind", "flatgrp"])
        assert prob is None and name == f"{kind}.fits"


def test_kind_case_upper_lower_i_goly_bez_zmian():
    """`case` upper/lower; goły `kind` i dict bez `case` = wartość jak w bazie (wsteczna zgodność)."""
    f = _facts(kind="master_flat")
    assert naming.compose_name(f, DT, template=[{"t": "kind", "case": "upper"}])[0] == "MASTER_FLAT.fits"
    assert naming.compose_name(_facts(kind="LIGHT"), DT,
                               template=[{"t": "kind", "case": "lower"}])[0] == "light.fits"
    assert naming.compose_name(f, DT, template=["kind"])[0] == "master_flat.fits"
    assert naming.compose_name(f, DT, template=[{"t": "kind"}])[0] == "master_flat.fits"


def test_trail_dokleja_separator_przed_rozszerzeniem():
    assert naming.compose_name(_facts(), DT, template=["kind", "exp", "trail"])[0] == "light_300s_.fits"


def test_trail_nie_na_koncu_valueerror():
    with pytest.raises(ValueError, match="trail"):
        naming.compose_name(_facts(), DT, template=["trail", "kind"])
    with pytest.raises(ValueError, match="trail"):
        naming.validate_template({"light": ["kind", "trail", "exp"]})


def test_validate_template_case():
    naming.validate_template(WZOR_SIOSTR)                            # poprawny wzór nie rzuca
    with pytest.raises(ValueError, match="case|wielkość"):
        naming.validate_template([{"t": "kind", "case": "title"}])


def test_domyslny_wzor_bez_nowych_tokenow():
    """Regresja: domyślny wzór nie dostał nowych tokenów - nazwy sprzed zmiany bez zmian."""
    assert naming.DEFAULT_TEMPLATE == ("datetime", "object", "kind", "filter", "exp", "disc")
    name, _ = naming.compose_name(_facts(), DT)
    assert name == "20260808_215845_CTB1_light_OIII_300s_abc123def456.fits"


# ============================================================ run_rename

def _row(**kw):
    base = {"frame_id": 1, "filetype": "fits", "kind": "light", "filter_canon": "OIII",
            "sha1_data": SHA, "object_canon": "CTB1", "object_raw": "CTB 1",
            "date_obs": "2026-08-08T21:58:45.853", "exptime": 300.0,
            "location_id": 10, "path": r"R:\A\CTB 1_LIGHT_O_300.00s_0000.fits", "mtime": "111",
            "flat_master_id": 7, "flat_paths": f'["{MASTER.replace(chr(92), chr(92) * 2)}"]'}
    base.update(kw)
    return base


def test_run_rename_wzor_siostr_i_problem_flatu_jako_skip():
    rows = [_row(), _row(frame_id=2, location_id=11, path=r"R:\A\b.fits", sha1_data="ff" * 9,
                         date_obs="2026-08-08T22:04:02", flat_paths="[]")]
    by = {r["frame_id"]: [r] for r in rows}
    run = naming.run_rename([1, 2], targets_fn=lambda ids: [r for i in ids for r in by.get(i, [])],
                            source="date_obs", offset_hours=0, template=WZOR_SIOSTR)
    assert [os.path.basename(p.new_path) for p in run.touched] == \
        ["CTB1_20260808_215845_LIGHT_OIII_300s_FLATGRP_202511010_.fits"]
    assert len(run.skipped) == 1 and "bez obecnej kopii" in run.skipped[0].reason


def test_run_rename_wiersz_bez_kolumn_flatu_noflat():
    """Źródło targetów bez kolumn ogniwa (stary kształt wiersza) = brak flatu, bez KeyError."""
    row = {k: v for k, v in _row().items() if not k.startswith("flat_")}
    run = naming.run_rename([1], targets_fn=lambda ids: [row], source="date_obs", offset_hours=0,
                            template=["kind", "flatgrp"])
    assert os.path.basename(run.touched[0].new_path) == "light_FLATGRP_NOFLAT.fits"


# ============================================================ queries.rename_frame_targets (DB)

def test_targets_ogniwo_flatu_bez_mnozenia_wierszy(tmp_path):
    """Dwie obecne kopie mastera flat → JEDEN wiersz lighta z dwiema ścieżkami w `flat_paths`;
    light bez ogniwa → `flat_master_id` NULL. Liczba wierszy = liczba kopii LIGHTA (silnik)."""
    con = db.open_db(str(tmp_path / "f.db"))
    light, _ = repo.upsert_frame(con, sha1_data="L1", kind="light", filetype="fits", camera_id=None, now=NOW)
    bez, _ = repo.upsert_frame(con, sha1_data="L2", kind="light", filetype="fits", camera_id=None, now=NOW)
    master, _ = repo.upsert_frame(con, sha1_data="M1", kind="master_flat", filetype="xisf",
                                  camera_id=None, now=NOW)
    repo.add_location(con, frame_id=light, volume="V", path=r"R:\L\a.fits", mtime="1", now=NOW)
    repo.add_location(con, frame_id=bez, volume="V", path=r"R:\L\b.fits", mtime="1", now=NOW)
    repo.add_location(con, frame_id=master, volume="V", path=MASTER, mtime="1", now=NOW)
    repo.add_location(con, frame_id=master, volume="W", path=MASTER.replace("R:", "F:"), mtime="1", now=NOW)
    repo.link_calibration(con, light_frame_id=light, master_frame_id=master, relation="flat", now=NOW)

    rows = queries.rename_frame_targets(con, [light, bez])
    assert [r["frame_id"] for r in rows] == [light, bez]
    by = {r["frame_id"]: r for r in rows}
    assert by[light]["flat_master_id"] == master and by[bez]["flat_master_id"] is None
    facts = naming._facts_of(by[light])
    assert sorted(facts["flat_paths"]) == sorted([MASTER, MASTER.replace("R:", "F:")])
    assert naming.compose_name(facts, DT, template=["flatgrp"])[0] == "FLATGRP_202511010.fits"
    assert naming.compose_name(naming._facts_of(by[bez]), DT, template=["flatgrp"])[0] == \
        "FLATGRP_NOFLAT.fits"
    con.close()
