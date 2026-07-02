"""Połączenie + runner migracji (user_version, idempotencja, FK, jawny błąd dla bazy v1)."""
import pytest

from horreum import db


def test_migracja_ustawia_user_version(tmp_path):
    con = db.connect(str(tmp_path / "h.db"))
    assert db._user_version(con) == 0
    db.migrate(con)
    assert db._user_version(con) == db.SCHEMA_VERSION == 2
    con.close()


def test_migracja_idempotentna(tmp_path):
    """Druga migracja na zmigrowanej bazie = no-op (nie wybucha 'table already exists')."""
    path = str(tmp_path / "h.db")
    con = db.open_db(path)
    con.close()
    con2 = db.open_db(path)               # ponowne open_db migruje znów — musi być no-op
    assert db._user_version(con2) == 2
    con2.close()


def test_przedpotopowa_baza_v1_jawny_blad(tmp_path):
    """Baza v1 (sprzed przejścia fitsmirror) nie ma ścieżki migracji — migrate() rzuca JAWNY
    RuntimeError zamiast wybuchać w połowie skryptu 0002 (D-A/R2#12; rama ŚWIEŻA-BAZA)."""
    path = str(tmp_path / "old.db")
    con = db.connect(path)
    con.execute("PRAGMA user_version = 1")
    with pytest.raises(RuntimeError, match="sprzed przejścia"):
        db.migrate(con)
    con.close()


def test_foreign_keys_on(tmp_path):
    con = db.connect(str(tmp_path / "h.db"))
    assert con.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    con.close()
