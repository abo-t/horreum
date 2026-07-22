"""Oś KALIBRACJI — przepis klatki sprzętowej (C2, #6): precedencja, komplet, idempotencja."""
import pytest

from horreum import db, repo
from horreum.calibration import (
    KIND_RECIPE, missing_facts, profile_key, run_calibration,
)
from horreum.grouper import NO_TELESCOPE_KINDS

NOW = "2026-07-22T12:00:00+00:00"
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


def _frame(con, *, kind, sha1, raw_json="{}", path=None, config_id=None, filter_canon=None,
           exptime=None, gain=None, offset_adu=None, xbinning=1):
    cur = con.execute(
        "INSERT INTO frame(sha1_data, kind, filetype, camera_id, config_id, filter_canon, "
        "first_seen_at) VALUES (?, ?, 'xisf', 1, ?, ?, ?)",
        (sha1, kind, config_id, filter_canon, NOW))
    fid = cur.lastrowid
    con.execute("INSERT INTO header(frame_id, raw_json, exptime, gain, offset_adu, xbinning) "
                "VALUES (?, ?, ?, ?, ?, ?)", (fid, raw_json, exptime, gain, offset_adu, xbinning))
    if path:
        con.execute("INSERT INTO location(frame_id, volume, path, present) VALUES (?, 'V', ?, 1)",
                    (fid, path))
    con.commit()
    return fid


def test_masterdark_bierze_nastawy_ze_sciezki(con):
    """Nagłówek mastera milczy (SET-TEMP/GAIN/OFFSET = 0 na 111 masterów), więc fakty przychodzą
    ze ŚCIEŻKI i zostają ZAPISANE (`source='path'`) — nie są re-derywowane co przebieg."""
    fid = _frame(con, kind="master_dark", sha1="d1", path=MASTERDARK, exptime=300.0)
    s = run_calibration(con, now=NOW)
    assert s.frames == 1 and s.profiles_proposed == 1 and s.incomplete == 0
    assert s.facts_recorded == 3                       # gain + offset + set_temp

    prof = con.execute("SELECT * FROM calibration_profile").fetchone()
    assert prof["recipe_class"] == "dark"
    assert (prof["gain"], prof["offset_adu"], prof["set_temp_c"]) == (100, 21, -10)
    assert prof["exptime"] == 300.0                    # czas z NAGŁÓWKA, nie ze ścieżki
    assert con.execute("SELECT calibration_profile_id FROM frame WHERE id = ?",
                       (fid,)).fetchone()[0] == prof["id"]
    facts = {r["key"]: r["source"] for r in con.execute("SELECT key, source FROM calibration_fact")}
    assert facts == {"gain": "path", "offset_adu": "path", "set_temp_c": "path"}


def test_wpis_uzytkownika_bije_sciezke(con):
    """Precedencja D-C-1: `user` > `header` > `path`. Wpis człowieka przebija fakt ze ścieżki
    i NIE jest przez niego nadpisywany przy kolejnym przebiegu."""
    fid = _frame(con, kind="master_dark", sha1="d1", path=MASTERDARK, exptime=300.0)
    run_calibration(con, now=NOW)
    repo.record_calibration_fact(con, frame_id=fid, key="set_temp_c", value=-13,
                                 source="user", now=NOW, actor="user:local")
    run_calibration(con, now=NOW)

    row = con.execute("SELECT value, source FROM calibration_fact WHERE frame_id = ? "
                      "AND key = 'set_temp_c'", (fid,)).fetchone()
    assert (row["value"], row["source"]) == ("-13", "user")        # ścieżka NIE odbiła wpisu
    prof_id = con.execute("SELECT calibration_profile_id FROM frame WHERE id = ?",
                          (fid,)).fetchone()[0]
    assert con.execute("SELECT set_temp_c FROM calibration_profile WHERE id = ?",
                       (prof_id,)).fetchone()[0] == -13


def test_brak_kompletu_to_brak_przepisu_i_zbiorczy_review(con):
    """Klatka bez kompletu NIE dostaje przepisu (sentinel w kluczu zlewałby różne nieznane nastawy)
    — zostaje z NULL-em i JEDNYM zbiorczym `calibration.review_summary`, już w C2."""
    _frame(con, kind="master_dark", sha1="d1", path=r"R:\ASTRO_\inne\master_bez_wzorca.xisf",
           exptime=300.0)
    s = run_calibration(con, now=NOW)
    assert s.incomplete == 1 and s.profiles_proposed == 0
    assert list(s.reasons) == ["dark: brak set_temp_c, gain, offset_adu"]
    assert con.execute("SELECT count(*) FROM frame WHERE calibration_profile_id IS NOT NULL"
                       ).fetchone()[0] == 0
    ev = con.execute("SELECT count(*) FROM event WHERE verb = 'calibration.review_summary'"
                     ).fetchone()[0]
    assert ev == 1                                     # ZBIORCZY, nie per klatka


def test_flat_bez_filtra_na_kamerze_kolorowej_ma_komplet(con):
    """Brak filtra to FAKT, nie luka (798 flatów bez FILTER to w 100 % kamery kolorowe) — flat
    dostaje przepis, a `filter_canon` NULL ma w kluczu STAŁĄ reprezentację."""
    _frame(con, kind="master_flat", sha1="f1", config_id=1, filter_canon=None)
    _frame(con, kind="master_flat", sha1="f2", config_id=1, filter_canon="Ha")
    s = run_calibration(con, now=NOW)
    assert s.incomplete == 0 and s.profiles_proposed == 2
    keys = {r[0] for r in con.execute("SELECT profile_key FROM calibration_profile")}
    assert keys == {"flat|cam=1|bin=1|tel=1|filt=~", "flat|cam=1|bin=1|tel=1|filt=Ha"}


def test_master_i_surowa_klatka_dziela_przepis(con):
    """Przedrostek `master_` schodzi do `recipe_class`: master i klatka surowa tej samej nastawy
    trafiają do JEDNEGO przepisu — inaczej rodowód nie miałby czego z czym łączyć."""
    _frame(con, kind="master_flat", sha1="f1", config_id=1, filter_canon="Ha")
    _frame(con, kind="flat", sha1="f2", config_id=1, filter_canon="Ha")
    s = run_calibration(con, now=NOW)
    assert s.frames == 2 and s.profiles_proposed == 1
    assert con.execute("SELECT count(DISTINCT calibration_profile_id) FROM frame "
                       "WHERE calibration_profile_id IS NOT NULL").fetchone()[0] == 1


def test_idempotencja_drugi_przebieg_zero_zmian_zero_eventow(con):
    """Drugi przebieg na niezmienionych danych = zero nowych wierszy i ZERO eventów."""
    _frame(con, kind="master_dark", sha1="d1", path=MASTERDARK, exptime=300.0)
    _frame(con, kind="master_flat", sha1="f1", config_id=1, filter_canon="Ha")
    run_calibration(con, now=NOW)
    przed = con.execute("SELECT count(*) FROM event").fetchone()[0]

    s2 = run_calibration(con, now="2026-07-22T13:00:00+00:00")
    assert (s2.profiles_proposed, s2.profiles_assigned, s2.facts_recorded) == (0, 0, 0)
    assert con.execute("SELECT count(*) FROM event").fetchone()[0] == przed


def test_klucz_odporny_na_typ_z_naglowka(con):
    """W3: `header.gain` jest kolumną TEXT, a ze ścieżki gain przychodzi jako int — obie drogi
    muszą dać TEN SAM klucz, inaczej jedna nastawa rozpada się na dwa przepisy."""
    a = {"camera_id": 1, "xbinning": 1, "exptime": 300.0, "set_temp_c": -10,
         "gain": 100, "offset_adu": 21}
    assert profile_key("dark", a) == "dark|cam=1|bin=1|exp=300.000|t=-10|g=100|o=21"
    assert missing_facts("dark", a) == ()
    assert missing_facts("dark", dict(a, gain=None)) == ("gain",)


def test_jedna_mapa_rodzajow_dla_obu_osi():
    """SPOT: `grouper.NO_TELESCOPE_KINDS` wyprowadza się z `KIND_RECIPE`, nie żyje obok niej.
    Wartość pinowana, bo dark na osi teleskopu budowałby configi pod cudzą optyką."""
    assert NO_TELESCOPE_KINDS == frozenset({"dark", "bias", "master_dark", "master_bias"})
    assert NO_TELESCOPE_KINDS == {k for k, (_c, axis) in KIND_RECIPE.items() if not axis}
    assert "light" not in KIND_RECIPE                  # light nie ma przepisu z definicji
