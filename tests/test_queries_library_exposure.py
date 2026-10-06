"""Read-model godzin biblioteki obiektów (`queries.library_exposure`, FH-10) - logika BEZ Qt.

Godziny liczą wyłącznie lighty niezastąpione z nagłówkiem; master i klatka zastąpiona liczą się
w kolumnie „Klatki" (`library_objects`), ale nie w godzinach. Filtr teleskopu idzie przez kanon
(`telescope_canonical`), więc klatki scalonego członka rolują się pod teleskop docelowy."""
from horreum import db, repo
from horreum.gui import portfolio, queries

from fixture_s8 import NOW, seed


def _baza(tmp_path):
    con = db.open_db(str(tmp_path / "godziny.db"))
    ids = seed(con)
    fr = ids["frames"]
    obj, _ = repo.upsert_object(con, canon="NGC7000", catalog="NGC", kind="deep_sky", now=NOW)
    master, _ = repo.upsert_frame(con, sha1_data="sha-master", kind="master_light", filetype="fits",
                                  camera_id=ids["cam1"], now=NOW)
    repo.assign_config(con, frame_id=master, config_id=ids["cfg_a"], now=NOW)
    naswietlenia = {fr["a1"]: 600.0, fr["a2"]: 600.0, fr["b1"]: 300.0, fr["b2"]: None,
                    fr["c1"]: 100.0, master: 3600.0}
    for fid, exptime in naswietlenia.items():
        con.execute("INSERT INTO header (frame_id, raw_json, exptime) VALUES (?, '{}', ?)",
                    (fid, exptime))
        con.execute("UPDATE frame SET object_id = ? WHERE id = ?", (obj, fid))
    con.execute("UPDATE frame SET superseded_by = ? WHERE id = ?", (fr["a1"], fr["a2"]))
    con.commit()
    return con, ids, obj


def _godziny(con, **filtry):
    return portfolio.summarize(queries.library_exposure(con, **filtry))


def test_master_i_zastapiona_nie_doliczaja_godzin_a_klatki_je_licza(tmp_path):
    """Falsyfikator: zdejmij `f.kind = 'light'` albo `f.superseded_by IS NULL` z zapytania -
    suma urośnie o 3600 s mastera albo o 600 s ducha a2."""
    con, ids, obj = _baza(tmp_path)
    try:
        wpis = _godziny(con)[obj]
        assert wpis["total_secs"] == 600.0 + 300.0 + 100.0
        assert wpis["n_null"] == 1                                 # b2 bez EXPTIME, jawnie
        klatki = {r["id"]: r["frame_count"] for r in queries.library_objects(con)}
        assert klatki[obj] == 6, "master i zastąpiona zostają w kolumnie Klatki"
    finally:
        con.close()


def test_filtr_teleskopu_idzie_przez_kanon_po_scaleniu(tmp_path):
    """Przed scaleniem teleskop A ma tylko a1 (a2 zastąpiona, master bez godzin). Po scaleniu B w A
    klatki B rolują się pod A, tak jak w `library_objects`.

    Falsyfikator: filtruj po `c.telescope_id` zamiast `tc.canon_id` - po scaleniu A zostaje z 600 s."""
    con, ids, obj = _baza(tmp_path)
    try:
        assert _godziny(con, telescope_id=ids["A"])[obj]["total_secs"] == 600.0
        assert _godziny(con, telescope_id=ids["C"])[obj]["total_secs"] == 100.0
        repo.merge_telescope(con, source_id=ids["B"], target_id=ids["A"], now=NOW)
        wpis = _godziny(con, telescope_id=ids["A"])[obj]
        assert wpis["total_secs"] == 600.0 + 300.0 and wpis["n_null"] == 1
        assert _godziny(con, telescope_id=ids["B"]) == {}
    finally:
        con.close()
