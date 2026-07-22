"""Schemat 0002 + 0003 — tabele/widoki istnieją, kształt zgodny z briefem przejścia §8
i briefem writebacku §2 (staging krok 4)."""
import sqlite3

import pytest

from horreum import db

EXPECTED_TABLES = {
    "frame", "location", "header", "cards", "camera", "telescope", "config",
    "object", "object_alias", "event", "saved_query",
    "calibration", "integration", "integration_input",
    # 0003 — staging writebacku (krok 4)
    "pending_changes", "commits", "header_backups", "macros",
    # 0004 — oś obserwatorium
    "observatory",
}


def _names(con, typ):
    return {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type = ?", (typ,))}


def _unique_cols(con, table):
    uniq = set()
    for row in con.execute(f"PRAGMA index_list({table})"):
        if row[2]:  # unique flag
            for ic in con.execute(f"PRAGMA index_info({row[1]})"):
                uniq.add(ic[2])
    return uniq


def test_wszystkie_tabele_powstaly(tmp_path):
    con = db.open_db(str(tmp_path / "h.db"))
    assert EXPECTED_TABLES <= _names(con, "table")
    con.close()


def test_widok_telescope_canonical(tmp_path):
    con = db.open_db(str(tmp_path / "h.db"))
    assert "telescope_canonical" in _names(con, "view")
    con.close()


def test_frame_sha1_data_unique_i_fakty_kopii_na_location(tmp_path):
    """Tożsamość frame = sha1_data (UNIQUE) + flaga degeneracji; fakty kopii (file_sha1/
    header_hash/hdu_index/compressed/size_bytes) mieszkają NA LOCATION, nie na frame (R2#6)."""
    con = db.open_db(str(tmp_path / "h.db"))
    frame_cols = {r[1] for r in con.execute("PRAGMA table_info(frame)")}
    assert {"sha1_data", "sha1_data_uncomputable"} <= frame_cols
    assert "sha1" not in frame_cols and "size_bytes" not in frame_cols
    assert "sha1_data" in _unique_cols(con, "frame")
    loc_cols = {r[1] for r in con.execute("PRAGMA table_info(location)")}
    assert {"file_sha1", "header_hash", "hdu_index", "compressed", "size_bytes"} <= loc_cols
    con.close()


def test_telescope_canon_nocase_i_camera_model_unique(tmp_path):
    """Oś TELESKOP: telescop_canon UNIQUE COLLATE NOCASE (bezpiecznik 'RC8 '/'rc8');
    oś KAMERA: model_canon UNIQUE, pixel_um nullable + pixel_conflict (stan)."""
    con = db.open_db(str(tmp_path / "h.db"))
    tel_cols = {r[1] for r in con.execute("PRAGMA table_info(telescope)")}
    assert "telescop_canon" in tel_cols and "telescop_hint" not in tel_cols
    assert "telescop_canon" in _unique_cols(con, "telescope")
    # NOCASE realnie działa: INSERT 'RC8', SELECT 'rc8' trafia (sam DDL nie wystarczy za dowód)
    con.execute("INSERT INTO telescope(telescop_canon, status, created_at) "
                "VALUES ('RC8', 'proposed', 't')")
    assert con.execute("SELECT count(*) FROM telescope WHERE telescop_canon = 'rc8'").fetchone()[0] == 1
    con.rollback()

    cam_cols = {r[1] for r in con.execute("PRAGMA table_info(camera)")}
    assert {"model_canon", "pixel_um", "pixel_conflict"} <= cam_cols
    assert "model_canon" in _unique_cols(con, "camera")
    header_cols = {r[1] for r in con.execute("PRAGMA table_info(header)")}
    assert "focratio_norm" not in header_cols and "focratio_norm_src" not in header_cols
    con.close()


def test_szkielet_przyszly_pusty(tmp_path):
    """calibration/integration* istnieją, ale puste (nie projektujemy pod dane, których nie ma)."""
    con = db.open_db(str(tmp_path / "h.db"))
    for t in ("calibration", "integration", "integration_input"):
        assert con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] == 0
    con.close()


def test_user_version_v8_po_migracji(tmp_path):
    """0008 podnosi user_version do 8 (świeża baza leci 0002→…→0008 sekwencyjnie)."""
    con = db.open_db(str(tmp_path / "h.db"))
    assert con.execute("PRAGMA user_version").fetchone()[0] == 8
    assert db.SCHEMA_VERSION == 8
    con.close()


def test_0006_marker_czytelnosci_kopii(tmp_path):
    """0006 (#13): location.unreadable_since istnieje, DEFAULT NULL (czytelna do dowodu). Migracja
    v5→v6 idempotentna (drugie open_db = no-op, nie „duplicate column"). Świeża baza = od razu v6."""
    path = str(tmp_path / "h.db")
    con = db.open_db(path)
    loc_cols = {r[1] for r in con.execute("PRAGMA table_info(location)")}
    assert "unreadable_since" in loc_cols
    con.close()
    con2 = db.open_db(path)                              # ponowna migracja: no-op, nie duplikuje kolumny
    assert con2.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    assert {r[1] for r in con2.execute("PRAGMA table_info(location)")} == loc_cols
    con2.close()


def test_0007_backup_hdu_nullable_z_danymi(tmp_path):
    """0007 (P6/D-X-14): `header_backups.hdu_index` NULLABLE — XISF nie ma HDU (D-X-7), a backup
    z NULL-em musi wejść PRZED `os.replace`, nie wybuchnąć po nim. Przebudowa tabeli PRZENOSI dane
    (append-only = historia undo) i odtwarza resztę kontraktu: FK, UNIQUE, CHECK, indeks."""
    path = str(tmp_path / "h.db")
    con = db.connect(path)
    con.executescript(db._migration_sql("0002_initial.sql"))     # zatrzymaj się na v3 (przed 0007)
    con.executescript(db._migration_sql("0003_writeback.sql"))
    con.execute("PRAGMA user_version = 3")
    con.execute("INSERT INTO frame(sha1_data, kind, filetype, first_seen_at) "
                "VALUES ('s1','light','fits','t')")
    con.execute("INSERT INTO location(frame_id, volume, path) VALUES (1,'V','p')")
    con.execute("INSERT INTO location(frame_id, volume, path) VALUES (1,'V','p2')")   # kopia XISF
    con.execute("INSERT INTO commits(run_id) VALUES ('r1')")
    con.execute("INSERT INTO header_backups(commit_id, location_id, hdu_index, header_text, post_hash) "
                "VALUES (1, 1, 0, 'SIMPLE = T', 'h0')")
    con.commit()
    con.close()

    con = db.open_db(path)                                       # v3 → v7 (0007 przebudowuje tabelę)
    assert con.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    row = con.execute("SELECT commit_id, location_id, hdu_index, header_text, post_hash "
                      "FROM header_backups").fetchone()
    assert tuple(row) == (1, 1, 0, 'SIMPLE = T', 'h0')           # stary wiersz PRZEŻYŁ przebudowę
    hdu = {r[1]: r for r in con.execute("PRAGMA table_info(header_backups)")}["hdu_index"]
    assert hdu[3] == 0                                            # notnull zdjęty
    con.execute("INSERT INTO header_backups(commit_id, location_id, hdu_index, header_text, post_hash) "
                "VALUES (1, 2, NULL, '<xisf/>', 'h1')")           # ← przed 0007: IntegrityError
    assert con.execute("SELECT count(*) FROM header_backups WHERE hdu_index IS NULL").fetchone()[0] == 1
    con.rollback()
    # kontrakt reszty kolumn odtworzony 1:1 (przebudowa nie jest okazją do rozluźnienia)
    for sql in (
        "INSERT INTO header_backups(commit_id, location_id, hdu_index, header_text, post_hash) "
        "VALUES (1, 2, NULL, '', 'h')",                           # CHECK length > 0
        "INSERT INTO header_backups(commit_id, location_id, hdu_index, header_text, post_hash) "
        "VALUES (999, 2, NULL, 'x', 'h')",                        # FK commits
        "INSERT INTO header_backups(commit_id, location_id, hdu_index, header_text, post_hash) "
        "VALUES (1, 1, NULL, 'x', 'h')",                          # UNIQUE(commit_id, location_id)
    ):
        with pytest.raises(sqlite3.IntegrityError):
            con.execute(sql)
        con.rollback()
    assert "idx_header_backups_commit" in _names(con, "index")
    con.close()


def test_os_obserwatorium_tabela_widok_kolumna(tmp_path):
    """0004: tabela observatory (lat/lon NOT NULL = seed zamrożony; merged_into self-FK; name nullable
    NIE-unique — tożsamość geometryczna, nie string), widok observatory_canonical, frame.observatory_id."""
    con = db.open_db(str(tmp_path / "h.db"))
    obs_cols = {r[1]: r for r in con.execute("PRAGMA table_info(observatory)")}
    assert {"id", "name", "lat", "lon", "elev", "merged_into", "status", "created_at"} <= set(obs_cols)
    assert obs_cols["lat"][3] == 1 and obs_cols["lon"][3] == 1     # notnull flag (seed zamrożony)
    assert "name" not in _unique_cols(con, "observatory")          # nazwa NIE jest kluczem tożsamości
    assert "observatory_canonical" in _names(con, "view")
    frame_cols = {r[1] for r in con.execute("PRAGMA table_info(frame)")}
    assert "observatory_id" in frame_cols
    assert con.execute("SELECT count(*) FROM observatory").fetchone()[0] == 0    # pusta po migracji
    con.close()


def test_staging_writeback_kluczowany_location(tmp_path):
    """Staging krok 4 (brief writeback §2): pending_changes/header_backups kluczowane LOCATION
    (fizyczny plik), nie frame; pending ma kotwicę expected_header_hash (R#7); header_backups
    UNIQUE(commit_id, location_id); staging PUSTY po migracji."""
    con = db.open_db(str(tmp_path / "h.db"))
    pend_cols = {r[1] for r in con.execute("PRAGMA table_info(pending_changes)")}
    assert {"location_id", "expected_header_hash", "op", "status"} <= pend_cols
    assert "file_id" not in pend_cols and "frame_id" not in pend_cols
    bkp_cols = {r[1] for r in con.execute("PRAGMA table_info(header_backups)")}
    assert {"location_id", "post_hash", "header_text", "hdu_index"} <= bkp_cols
    assert {"commit_id", "location_id"} <= _unique_cols(con, "header_backups")
    for t in ("pending_changes", "commits", "header_backups", "macros"):
        assert con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] == 0
    con.close()


def test_0008_nastawa_jest_odczytem_z_zeznania_nie_kopia(tmp_path):
    """0008 (D-C-2): `header.set_temp` to kolumna GENERATED z `raw_json` — nastawa jest ODCZYTYWANA,
    nie kopiowana, więc migracja nie ma backfillu i wartość nie może się zestarzeć po writebacku.

    `CAST(... AS REAL)` jest konieczny, nie kosmetyczny: `json_extract` oddaje `-10.0` jako REAL
    dla FITS-ów i jako TEXT dla XISF-ów (zmierzone na archiwum: 202 klatki) — bez rzutu ta sama
    nastawa rozpadłaby się na dwie wartości (W3, ta sama pułapka co przy kamerach).

    PUŁAPKA: `PRAGMA table_info` NIE POKAZUJE kolumn generowanych — widać je dopiero w `table_xinfo`.
    Test schematu szukający `set_temp` w `table_info` dałby fałszywy alarm."""
    con = db.open_db(str(tmp_path / "h.db"))
    assert "set_temp" not in {r[1] for r in con.execute("PRAGMA table_info(header)")}
    assert "set_temp" in {r[1] for r in con.execute("PRAGMA table_xinfo(header)")}

    con.execute("INSERT INTO frame(sha1_data, kind, filetype, first_seen_at) "
                "VALUES ('a', 'light', 'fits', 't')")
    con.execute("INSERT INTO header(frame_id, raw_json) VALUES (1, '{\"SET-TEMP\": -10.0}')")
    con.execute("INSERT INTO frame(sha1_data, kind, filetype, first_seen_at) "
                "VALUES ('b', 'light', 'xisf', 't')")
    con.execute("INSERT INTO header(frame_id, raw_json) VALUES (2, '{\"SET-TEMP\": \"-10.0\"}')")
    con.execute("INSERT INTO frame(sha1_data, kind, filetype, first_seen_at) "
                "VALUES ('c', 'master_dark', 'xisf', 't')")
    con.execute("INSERT INTO header(frame_id, raw_json) VALUES (3, '{}')")

    rows = {r[0]: r[1] for r in con.execute("SELECT frame_id, set_temp FROM header")}
    assert rows[1] == -10.0                      # FITS: REAL
    assert rows[2] == -10.0                      # XISF: string zrzutowany tym samym CASTem
    assert rows[1] == rows[2]                    # jedna nastawa == jedna wartość (W3)
    assert rows[3] is None                       # brak karty = BRAK WPISU, nigdy 0
    assert con.execute("SELECT count(DISTINCT set_temp) FROM header "
                       "WHERE set_temp IS NOT NULL").fetchone()[0] == 1
    con.close()


def test_0008_przepis_nie_powstaje_bez_kompletu(tmp_path):
    """0008: `calibration_profile` nie przyjmuje niekompletnego przepisu — CHECK per klasa pilnuje
    tego, czego warunkowy NOT NULL nie umie. Powód: sentinel w kluczu zlewałby DWA mastery
    o RÓŻNYCH, nieznanych nastawach w jeden przepis, a UNIQUE by tego nie złapał."""
    con = db.open_db(str(tmp_path / "h.db"))
    con.execute("INSERT INTO camera(model_canon, pixel_um, is_mono, created_at) "
                "VALUES ('ASI2600MM', 3.76, 1, 't')")
    con.execute("INSERT INTO telescope(telescop_canon, status, created_at) "
                "VALUES ('A140R', 'proposed', 't')")

    with pytest.raises(sqlite3.IntegrityError):          # dark bez temperatury = niekompletny
        con.execute("INSERT INTO calibration_profile(profile_key, recipe_class, camera_id, "
                    "xbinning, exptime, gain, offset_adu, created_at) "
                    "VALUES ('k1', 'dark', 1, 1, 300.0, 100, 21, 't')")
    with pytest.raises(sqlite3.IntegrityError):          # flat bez teleskopu = niekompletny
        con.execute("INSERT INTO calibration_profile(profile_key, recipe_class, camera_id, "
                    "xbinning, filter_canon, created_at) VALUES ('k2', 'flat', 1, 1, 'Ha', 't')")

    con.execute("INSERT INTO calibration_profile(profile_key, recipe_class, camera_id, xbinning, "
                "exptime, set_temp_c, gain, offset_adu, created_at) "
                "VALUES ('dark|cam=1|bin=1|exp=300.000|t=-10|g=100|o=21', 'dark', 1, 1, "
                "300.0, -10, 100, 21, 't')")
    con.execute("INSERT INTO calibration_profile(profile_key, recipe_class, camera_id, xbinning, "
                "telescope_id, filter_canon, created_at) "
                "VALUES ('flat|cam=1|bin=1|tel=1|filt=Ha', 'flat', 1, 1, 1, 'Ha', 't')")
    # flat kamery KOLOROWEJ: brak filtra to FAKT, nie luka — przechodzi
    con.execute("INSERT INTO calibration_profile(profile_key, recipe_class, camera_id, xbinning, "
                "telescope_id, created_at) VALUES ('flat|cam=1|bin=1|tel=1|filt=~', 'flat', 1, 1, 1, 't')")
    assert con.execute("SELECT count(*) FROM calibration_profile").fetchone()[0] == 3
    con.close()


def test_0008_fakt_nie_dubluje_zeznania(tmp_path):
    """0008: `calibration_fact` trzyma WYŁĄCZNIE fakty, których w nagłówku NIE MA — `source`
    dopuszcza 'user' i 'path', nigdy 'header' (D-C-2: zeznania nie kopiujemy, czytamy je wprost).
    Klucz `(frame_id, key)` — jeden fakt danego rodzaju na klatkę."""
    con = db.open_db(str(tmp_path / "h.db"))
    con.execute("INSERT INTO frame(sha1_data, kind, filetype, first_seen_at) "
                "VALUES ('a', 'master_dark', 'xisf', 't')")
    con.execute("INSERT INTO calibration_fact(frame_id, key, value, source, actor, created_at) "
                "VALUES (1, 'gain', '100', 'path', 'calibration', 't')")
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO calibration_fact(frame_id, key, value, source, actor, created_at) "
                    "VALUES (1, 'gain', '100', 'header', 'scan', 't')")
    with pytest.raises(sqlite3.IntegrityError):         # ten sam fakt drugi raz
        con.execute("INSERT INTO calibration_fact(frame_id, key, value, source, actor, created_at) "
                    "VALUES (1, 'gain', '0', 'user', 'user:local', 't')")
    con.close()
