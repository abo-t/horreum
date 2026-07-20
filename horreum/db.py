"""Połączenie + runner migracji (infrastruktura — DDL i pragma, NIE zapis domenowy).

Drugi (poza `horreum.repo`) sankcjonowany dom dla `con.execute*`: tu wolno DDL migracji
i PRAGMA, ale ZERO DML domenowego (INSERT/UPDATE/DELETE) — pilnuje tego meta-test AST
(`tests/test_repo_safety.py`). Wersjonowanie przez `PRAGMA user_version` (wbudowany licznik
SQLite) — bez tabeli bookkeepingu, więc bez INSERT-u w warstwie infra.
"""
import sqlite3
from importlib import resources

# (wersja, plik migracji) — kolejność rosnąca; user_version po zastosowaniu = wersja ostatniej.
# 0002 ZASTĘPUJE 0001 (przejście fitsmirror, D-A/R2#12): świeża baza dostaje od razu v2;
# przedpotopowa baza v1 (sprzed przejścia) nie ma ścieżki migracji — jawny błąd w migrate().
# 0003 to PRZYROST (staging writebacku, KROK 4): baza v2 dostaje puste tabele stagingu, świeża
# leci 0002→0003 sekwencyjnie. Zero zmian istniejących tabel (D3: re-skan, nie konwerter).
# 0004 to PRZYROST (oś OBSERWATORIUM): nowa tabela observatory + frame.observatory_id + widok
# observatory_canonical; baza v3 dostaje pustą oś (resolve_observatory wypełnia z cards).
# 0005 to PRZYROST (staging renamu "Nazwy z faktów"): nowa tabela pending_renames; zero zmian
# istniejących. Osobna od pending_changes (inny kształt path→path, inna kotwica mtime).
# 0006 to PRZYROST (#13): znacznik czytelności kopii — location.unreadable_since (NULL=czytelna,
# ISO=pierwsza nieudana próba). Zero zmian istniejących: ADD COLUMN, re-skan wypełnia (jak 0004).
MIGRATIONS = [
    (2, "0002_initial.sql"),
    (3, "0003_writeback.sql"),
    (4, "0004_observatory.sql"),
    (5, "0005_rename.sql"),
    (6, "0006_unreadable.sql"),
]
SCHEMA_VERSION = MIGRATIONS[-1][0]
_KNOWN_VERSIONS = frozenset({0} | {v for v, _ in MIGRATIONS})


def connect(path):
    """Otwórz bazę Horreum z FK ON i Row factory. `path` = plik albo ':memory:'.

    WAL + busy_timeout (PLAN_gui §5): GUI to długo żyjące połączenie RW, możliwy równoległy CLI/skan
    na tej samej bazie. WAL pozwala czytelnikom i jednemu writerowi współistnieć; busy_timeout daje
    czekanie zamiast natychmiastowego `database is locked`. To PRAGMA (infra), ZERO DML — meta-test
    AST przepuszcza. (`:memory:` ignoruje WAL — wraca 'memory', nieszkodliwe.)"""
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    con.execute("PRAGMA busy_timeout = 5000")
    return con


def _user_version(con):
    return con.execute("PRAGMA user_version").fetchone()[0]


def _migration_sql(filename):
    return resources.files("horreum.schema.migrations").joinpath(filename).read_text(encoding="utf-8")


def migrate(con):
    """Zastosuj migracje > bieżącej user_version. Idempotentne (druga próba = no-op).
    Zwraca wersję schematu po migracji.

    EXPECT: baza o wersji SPOZA łańcucha (np. v1 sprzed przejścia fitsmirror) → jawny błąd,
    nie cicha pół-migracja (0002 to pełny initial — na v1 wybuchłby w połowie skryptu).
    Świeżą bazę tworzy migracja; konwertera starej NIE ma (brief przejścia, rama ŚWIEŻA-BAZA)."""
    current = _user_version(con)
    if current not in _KNOWN_VERSIONS and current < SCHEMA_VERSION:
        raise RuntimeError(
            f"baza w wersji v{current} sprzed przejścia fitsmirror — brak ścieżki migracji; "
            f"utwórz świeżą bazę (horreum init) i zasil ją ponownie")
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
