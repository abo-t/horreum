"""Oś KALIBRACJI — RODOWÓD light↔master (C4, #6): dopasowanie po przepisie, reguła czasowa,
kubełki „czego brakuje", idempotencja, re-link przy bliższym masterze."""
import json

import pytest

from horreum import db, repo
from horreum.calibration import run_calibration
from horreum.lineage import run_lineage

NOW = "2026-07-23T12:00:00+00:00"
# Masterdark: header milczy, fakty (gain/offset/temp) idą ze ŚCIEŻKI — ten sam wzorzec co C2.
MASTERDARK = (r"R:\ASTRO_\CALIBRATION\masters\darks\ASI2600MM_100_21"
              r"\MASTERDARK_26MM_G100_O21_10_0300.000_EXPOSURE_300s.xisf")


@pytest.fixture
def con(tmp_path):
    c = db.open_db(str(tmp_path / "h.db"))
    c.execute("INSERT INTO camera(model_canon, pixel_um, is_mono, created_at) "
              "VALUES ('ASI2600MM', 3.76, 1, ?)", (NOW,))
    c.execute("INSERT INTO telescope(telescop_canon, status, created_at) "
              "VALUES ('A140R', 'proposed', ?)", (NOW,))
    c.execute("INSERT INTO config(telescope_id, camera_id, label, status, created_at) "
              "VALUES (1, 1, 'A140R x ASI2600MM', 'proposed', ?)", (NOW,))
    yield c
    c.close()


def _frame(con, *, kind, sha1, path=None, config_id=None, filter_canon=None, exptime=None,
           set_temp=None, gain=None, offset_adu=None, xbinning=1, date_obs=None):
    """Klatka + nagłówek. `set_temp` wchodzi przez `raw_json` (kolumna GENERATED), jak w realnym
    zeznaniu — light niesie nastawę, master nie (integracja ją zjada)."""
    raw = json.dumps({"SET-TEMP": set_temp}) if set_temp is not None else "{}"
    cur = con.execute(
        "INSERT INTO frame(sha1_data, kind, filetype, camera_id, config_id, filter_canon, "
        "first_seen_at) VALUES (?, ?, 'xisf', 1, ?, ?, ?)",
        (sha1, kind, config_id, filter_canon, NOW))
    fid = cur.lastrowid
    con.execute("INSERT INTO header(frame_id, raw_json, date_obs, exptime, gain, offset_adu, "
                "xbinning) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (fid, raw, date_obs, exptime, gain, offset_adu, xbinning))
    if path:
        con.execute("INSERT INTO location(frame_id, volume, path, present) VALUES (?, 'V', ?, 1)",
                    (fid, path))
    con.commit()
    return fid


def _light_dark(con, sha1, *, exptime=300.0, temp=-10, gain=100, offset=21, date="2024-01-01T00:00:00"):
    """Light z kompletnym przepisem DARKA — jego klucz musi zejść BAJTOWO z kluczem masterdarka
    ze ścieżki (szew header↔ścieżka)."""
    return _frame(con, kind="light", sha1=sha1, exptime=exptime, set_temp=temp, gain=gain,
                  offset_adu=offset, date_obs=date)


def test_light_linkuje_masterdark_szew_header_sciezka(con):
    """Klucz lightu z NAGŁÓWKA (SET-TEMP/gain/offset) == klucz masterdarka ze ŚCIEŻKI (`source='path'`).
    To najgorętszy szew: dwa różne źródła składają ten sam przepis."""
    md = _frame(con, kind="master_dark", sha1="d1", path=MASTERDARK, exptime=300.0,
                date_obs="2023-01-01T00:00:00")
    lid = _light_dark(con, "l1")
    run_calibration(con, now=NOW)
    s = run_lineage(con, now=NOW)

    assert s.lights == 1 and s.linked.get("dark") == 1
    row = con.execute("SELECT master_frame_id, relation, asserted_by, confidence FROM calibration "
                      "WHERE light_frame_id = ?", (lid,)).fetchone()
    assert (row["master_frame_id"], row["relation"]) == (md, "dark")
    assert (row["asserted_by"], row["confidence"]) == ("horreum", "recipe")
    assert con.execute("SELECT count(*) FROM event WHERE verb='calibration.linked'").fetchone()[0] == 1


def test_flat_wybiera_najblizszy_czasowo(con):
    """Profil FLAT z dwoma masterflatami różnej daty — light bierze BLIŻSZY czasowo, nie pierwszy."""
    stary = _frame(con, kind="master_flat", sha1="f_old", config_id=1, filter_canon="Ha",
                   date_obs="2022-01-01T00:00:00")
    nowy = _frame(con, kind="master_flat", sha1="f_new", config_id=1, filter_canon="Ha",
                  date_obs="2025-01-01T00:00:00")
    lid = _frame(con, kind="light", sha1="l1", config_id=1, filter_canon="Ha",
                 date_obs="2024-11-01T00:00:00")                 # bliżej `nowy`
    run_calibration(con, now=NOW)
    s = run_lineage(con, now=NOW)

    assert s.linked.get("flat") == 1
    mid = con.execute("SELECT master_frame_id FROM calibration WHERE light_frame_id=? AND relation='flat'",
                      (lid,)).fetchone()[0]
    assert mid == nowy and mid != stary


def test_remis_tie_break_min_id(con):
    """Dwa masterflaty o TEJ SAMEJ dacie (remis |Δ|) → MIN frame.id, deterministycznie."""
    m1 = _frame(con, kind="master_flat", sha1="fa", config_id=1, filter_canon="Ha",
                date_obs="2024-01-01T00:00:00")
    _frame(con, kind="master_flat", sha1="fb", config_id=1, filter_canon="Ha",
           date_obs="2024-01-01T00:00:00")
    lid = _frame(con, kind="light", sha1="l1", config_id=1, filter_canon="Ha",
                 date_obs="2024-06-01T00:00:00")
    run_calibration(con, now=NOW)
    run_lineage(con, now=NOW)
    mid = con.execute("SELECT master_frame_id FROM calibration WHERE light_frame_id=?", (lid,)).fetchone()[0]
    assert mid == m1                                             # niższy id wygrywa remis


def test_kalibrator_to_zawsze_master_nie_surowy(con):
    """Profil ma surowy flat I masterflat — light linkuje MASTER, nigdy surowy (brief C2 §5)."""
    _frame(con, kind="flat", sha1="raw", config_id=1, filter_canon="Ha",
           date_obs="2024-05-01T00:00:00")                       # surowy — BLIŻEJ lightu
    master = _frame(con, kind="master_flat", sha1="m", config_id=1, filter_canon="Ha",
                    date_obs="2022-01-01T00:00:00")              # master — DALEJ
    lid = _frame(con, kind="light", sha1="l1", config_id=1, filter_canon="Ha",
                 date_obs="2024-06-01T00:00:00")
    run_calibration(con, now=NOW)
    run_lineage(con, now=NOW)
    mid = con.execute("SELECT master_frame_id FROM calibration WHERE light_frame_id=?", (lid,)).fetchone()[0]
    assert mid == master                                         # mimo że surowy jest bliżej


def test_brak_przepisu_w_archiwum(con):
    """Light o przepisie, którego archiwum nie zna → kubełek „brak przepisu", zero wierszy."""
    _light_dark(con, "l1", exptime=999.0)                        # żaden master 999 s
    run_calibration(con, now=NOW)
    s = run_lineage(con, now=NOW)
    assert s.linked.get("dark", 0) == 0
    assert s.reasons.get("dark: brak przepisu w archiwum") == 1
    assert con.execute("SELECT count(*) FROM calibration").fetchone()[0] == 0


def test_brak_mastera_sa_tylko_surowe(con):
    """Profil istnieje (surowy flat), ale bez masterflata → kubełek „brak mastera"."""
    _frame(con, kind="flat", sha1="raw", config_id=1, filter_canon="Ha", date_obs="2024-01-01T00:00:00")
    _frame(con, kind="light", sha1="l1", config_id=1, filter_canon="Ha", date_obs="2024-02-01T00:00:00")
    run_calibration(con, now=NOW)
    s = run_lineage(con, now=NOW)
    assert s.reasons.get("flat: brak mastera (są tylko surowe)") == 1
    assert con.execute("SELECT count(*) FROM calibration WHERE relation='flat'").fetchone()[0] == 0


def test_niekompletny_przepis_lightu(con):
    """Light bez nastawy (brak SET-TEMP) → dark-przepis niekompletny → kubełek, nie klucz z sentinelem."""
    _frame(con, kind="master_dark", sha1="d1", path=MASTERDARK, exptime=300.0, date_obs="2023-01-01T00:00:00")
    _frame(con, kind="light", sha1="l1", exptime=300.0, gain=100, offset_adu=21,  # set_temp brak
           date_obs="2024-01-01T00:00:00")
    run_calibration(con, now=NOW)
    s = run_lineage(con, now=NOW)
    assert s.reasons.get("dark: niekompletny przepis lightu") == 1
    assert s.linked.get("dark", 0) == 0


def test_domkniecie_populacji_per_relacja(con):
    """Suma kubełków (linked + luki) == lighty, dla KAŻDEJ relacji — brama fałszywie zielona inaczej."""
    _frame(con, kind="master_dark", sha1="d1", path=MASTERDARK, exptime=300.0, date_obs="2023-01-01T00:00:00")
    _frame(con, kind="master_flat", sha1="f1", config_id=1, filter_canon="Ha", date_obs="2023-01-01T00:00:00")
    _light_dark(con, "l_ok", date="2024-01-01T00:00:00")         # dark linked; flat: brak przepisu (bez configu/filtra)
    _frame(con, kind="light", sha1="l_flat", config_id=1, filter_canon="Ha", exptime=999.0,
           date_obs="2024-01-01T00:00:00")                       # flat linked; dark: brak przepisu 999
    run_calibration(con, now=NOW)
    s = run_lineage(con, now=NOW)
    for rel in ("dark", "flat"):
        gaps = sum(n for powod, n in s.reasons.items() if powod.startswith(f"{rel}:"))
        assert s.linked.get(rel, 0) + gaps == s.lights == 2


def test_idempotencja(con):
    """Drugi przebieg na niezmienionych danych = zero zapisów i zero eventów rodowodu."""
    _frame(con, kind="master_dark", sha1="d1", path=MASTERDARK, exptime=300.0, date_obs="2023-01-01T00:00:00")
    _light_dark(con, "l1")
    run_calibration(con, now=NOW)
    run_lineage(con, now=NOW)
    ev1 = con.execute("SELECT count(*) FROM event WHERE verb='calibration.linked'").fetchone()[0]
    rows1 = con.execute("SELECT count(*) FROM calibration").fetchone()[0]
    s2 = run_lineage(con, now=NOW)
    assert not s2.linked_new
    assert con.execute("SELECT count(*) FROM event WHERE verb='calibration.linked'").fetchone()[0] == ev1
    assert con.execute("SELECT count(*) FROM calibration").fetchone()[0] == rows1


def test_relink_gdy_dojdzie_blizszy_master(con):
    """Nowy wsad z masterflatem bliższym czasowo → UPDATE + unlinked(stary) + linked(nowy), JEDEN wiersz."""
    stary = _frame(con, kind="master_flat", sha1="f_old", config_id=1, filter_canon="Ha",
                   date_obs="2020-01-01T00:00:00")
    lid = _frame(con, kind="light", sha1="l1", config_id=1, filter_canon="Ha",
                 date_obs="2024-06-01T00:00:00")
    run_calibration(con, now=NOW)
    run_lineage(con, now=NOW)
    assert con.execute("SELECT master_frame_id FROM calibration WHERE light_frame_id=?", (lid,)).fetchone()[0] == stary

    nowy = _frame(con, kind="master_flat", sha1="f_new", config_id=1, filter_canon="Ha",
                  date_obs="2024-05-01T00:00:00")                # bliżej lightu
    run_calibration(con, now=NOW)
    s = run_lineage(con, now=NOW)
    assert s.linked_new.get("flat") == 1                        # re-link policzony jako zmiana
    rows = con.execute("SELECT master_frame_id FROM calibration WHERE light_frame_id=? AND relation='flat'",
                       (lid,)).fetchall()
    assert len(rows) == 1 and rows[0][0] == nowy                # UNIQUE trzyma jeden wiersz
    assert con.execute("SELECT count(*) FROM event WHERE verb='calibration.unlinked'").fetchone()[0] == 1


def test_light_bez_date_obs_degeneruje_do_min_id_bez_crash(con):
    """Light bez `date_obs` w profilu wielo-masterowym → MIN frame.id, jawnie, nie crash."""
    m1 = _frame(con, kind="master_flat", sha1="fa", config_id=1, filter_canon="Ha", date_obs="2022-01-01T00:00:00")
    _frame(con, kind="master_flat", sha1="fb", config_id=1, filter_canon="Ha", date_obs="2025-01-01T00:00:00")
    lid = _frame(con, kind="light", sha1="l1", config_id=1, filter_canon="Ha", date_obs=None)
    run_calibration(con, now=NOW)
    run_lineage(con, now=NOW)
    assert con.execute("SELECT master_frame_id FROM calibration WHERE light_frame_id=?", (lid,)).fetchone()[0] == m1
