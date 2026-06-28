"""Połączenie + runner migracji (user_version, idempotencja, FK)."""
from horreum import db


def test_migracja_ustawia_user_version(tmp_path):
    con = db.connect(str(tmp_path / "h.db"))
    assert db._user_version(con) == 0
    db.migrate(con)
    assert db._user_version(con) == db.SCHEMA_VERSION == 1
    con.close()


def test_migracja_idempotentna(tmp_path):
    """Druga migracja na zmigrowanej bazie = no-op (nie wybucha 'table already exists')."""
    path = str(tmp_path / "h.db")
    con = db.open_db(path)
    con.close()
    con2 = db.open_db(path)               # ponowne open_db migruje znów — musi być no-op
    assert db._user_version(con2) == 1
    con2.close()


def test_foreign_keys_on(tmp_path):
    con = db.connect(str(tmp_path / "h.db"))
    assert con.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    con.close()
