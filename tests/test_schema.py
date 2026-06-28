"""Schemat 0001 — tabele/widoki istnieją, kształt zgodny z PLAN §1."""
from horreum import db

EXPECTED_TABLES = {
    "frame", "location", "header", "camera", "telescope", "config",
    "object", "object_alias", "event", "saved_query",
    "calibration", "integration", "integration_input",
}


def _names(con, typ):
    return {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type = ?", (typ,))}


def test_wszystkie_tabele_powstaly(tmp_path):
    con = db.open_db(str(tmp_path / "h.db"))
    assert EXPECTED_TABLES <= _names(con, "table")
    con.close()


def test_widok_telescope_canonical(tmp_path):
    con = db.open_db(str(tmp_path / "h.db"))
    assert "telescope_canonical" in _names(con, "view")
    con.close()


def test_frame_sha1_unique(tmp_path):
    """sha1 = tożsamość → UNIQUE (odwrócenie path-UNIQUE Custosa, PLAN §6)."""
    con = db.open_db(str(tmp_path / "h.db"))
    cols = {r[1]: r for r in con.execute("PRAGMA table_info(frame)")}
    assert "sha1" in cols
    idx = con.execute("PRAGMA index_list(frame)").fetchall()
    uniq_cols = set()
    for row in idx:
        if row[2]:  # unique flag
            for ic in con.execute(f"PRAGMA index_info({row[1]})"):
                uniq_cols.add(ic[2])
    assert "sha1" in uniq_cols
    con.close()


def test_szkielet_przyszly_pusty(tmp_path):
    """calibration/integration* istnieją, ale puste w plastrze B (nie projektujemy pod dane,
    których nie ma — PLAN §1.7)."""
    con = db.open_db(str(tmp_path / "h.db"))
    for t in ("calibration", "integration", "integration_input"):
        assert con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] == 0
    con.close()
