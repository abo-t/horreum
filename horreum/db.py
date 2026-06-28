"""Połączenie + runner migracji (infrastruktura — DDL i pragma, NIE zapis domenowy).

Drugi (poza `horreum.repo`) sankcjonowany dom dla `con.execute*`: tu wolno DDL migracji
i PRAGMA, ale ZERO DML domenowego (INSERT/UPDATE/DELETE) — pilnuje tego meta-test AST
(`tests/test_repo_safety.py`). Wersjonowanie przez `PRAGMA user_version` (wbudowany licznik
SQLite) — bez tabeli bookkeepingu, więc bez INSERT-u w warstwie infra.
"""
import sqlite3
from importlib import resources

# (wersja, plik migracji) — kolejność rosnąca; user_version po zastosowaniu = wersja ostatniej.
MIGRATIONS = [
    (1, "0001_initial.sql"),
]
SCHEMA_VERSION = MIGRATIONS[-1][0]


def connect(path):
    """Otwórz bazę Horreum z FK ON i Row factory. `path` = plik albo ':memory:'."""
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def _user_version(con):
    return con.execute("PRAGMA user_version").fetchone()[0]


def _migration_sql(filename):
    return resources.files("horreum.schema.migrations").joinpath(filename).read_text(encoding="utf-8")


def migrate(con):
    """Zastosuj migracje > bieżącej user_version. Idempotentne (druga próba = no-op).
    Zwraca wersję schematu po migracji."""
    current = _user_version(con)
    for version, filename in MIGRATIONS:
        if version > current:
            con.executescript(_migration_sql(filename))
            # PRAGMA nie przyjmuje bindowania — f-string z literału int (version z MIGRATIONS).
            con.execute(f"PRAGMA user_version = {int(version)}")
            current = version
    return current


def open_db(path):
    """Otwórz + zmigruj. Główne wejście dla CLI/skanu."""
    con = connect(path)
    migrate(con)
    return con
