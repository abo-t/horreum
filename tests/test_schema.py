"""Schemat 0002 + 0003 — tabele/widoki istnieją, kształt zgodny z briefem przejścia §8
i briefem writebacku §2 (staging krok 4)."""
from horreum import db

EXPECTED_TABLES = {
    "frame", "location", "header", "cards", "camera", "telescope", "config",
    "object", "object_alias", "event", "saved_query",
    "calibration", "integration", "integration_input",
    # 0003 — staging writebacku (krok 4)
    "pending_changes", "commits", "header_backups", "macros",
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


def test_user_version_v3_po_migracji(tmp_path):
    """0003 podnosi user_version do 3 (świeża baza leci 0002→0003 sekwencyjnie)."""
    con = db.open_db(str(tmp_path / "h.db"))
    assert con.execute("PRAGMA user_version").fetchone()[0] == 3
    assert db.SCHEMA_VERSION == 3
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
