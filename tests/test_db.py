"""Połączenie + runner migracji (user_version, idempotencja, FK, jawny błąd dla bazy v1)."""
import pytest

from horreum import db


def test_migracja_ustawia_user_version(tmp_path):
    con = db.connect(str(tmp_path / "h.db"))
    assert db._user_version(con) == 0
    db.migrate(con)
    # 0002 init + 0003 wb + 0004 obs + 0005 rename + 0006 unreadable + 0007 backup-hdu-nullable
    # + 0008 kalibracja + 0009 rodowód + 0010 kind_source (DSLR/RAW, #2)
    # + 0011 target_plan + telescope.in_park (planer T4) + 0012 rodowód stosów (I-2c)
    # + 0013 saved_query.spec_json (perspektywy w BAZIE, I-1)
    # + 0014 frame.superseded_by (zastąpienie tożsamości po podmianie pliku, #DR2/R4)
    # + 0015 frame.config_source (oś sprzętu wskazana ręką, #DR2/R1)
    # + 0016 integration.utc_offset_min + powód `offset_unknown` (odniesienie czasu, #DR2/R2)
    # + 0017 frame.object_cleared_id (pamięć nagrobka — co ręka zdjęła, R-S2b-3)
    # + 0018 frame.retired_at (wycofanie klatki ręką — D-OW-3/R2)
    # + 0019 location.unreadable_kind + unreadable_reason (rodzaj i powód nieczytelności, P4-2)
    # + 0020 integration.raw_unreferenced (uwaga obok werdyktu rodowodu, G2-1d)
    # + 0021 location: liczba/role obrazów + zeznanie nagłówka kopii z kotwicą hdr_hash
    # + 0022 inplace_op (dziennik zapisu w miejscu: faza operacji i izolacja lokacji, O5/Q8)
    assert db._user_version(con) == db.SCHEMA_VERSION == 22
    con.close()


def test_migracja_idempotentna(tmp_path):
    """Druga migracja na zmigrowanej bazie = no-op (nie wybucha 'table already exists')."""
    path = str(tmp_path / "h.db")
    con = db.open_db(path)
    con.close()
    con2 = db.open_db(path)               # ponowne open_db migruje znów — musi być no-op
    assert db._user_version(con2) == db.SCHEMA_VERSION
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


def _kolumny(con, tabela):
    return [r[1] for r in con.execute(f"PRAGMA table_info({tabela})")]


@pytest.mark.parametrize("wersja_w_tresci", [False, True])
def test_awaria_w_srodku_migracji_nie_zostawia_polowy_schematu(tmp_path, monkeypatch,
                                                               wersja_w_tresci):
    """Migracja pada PO pierwszym `ALTER TABLE` (symulacja: prawdziwy skrypt 0021 z błędną
    instrukcją na końcu). Wersja i schemat zostają sprzed migracji, a ponowne otwarcie przechodzi
    całą drogę do końca - dawniej `executescript` zatwierdzał kolumny po jednej, `user_version`
    zostawało stare i drugie otwarcie wybuchało na `duplicate column name`. Wariant z `PRAGMA
    user_version` w treści skryptu to wzór starych migracji (0008, 0009, 0012, 0013, 0016): numer
    ustawiony w środku też musi wrócić razem z resztą."""
    path = str(tmp_path / "h.db")
    pelne = list(db.MIGRATIONS)
    monkeypatch.setattr(db, "MIGRATIONS", [m for m in pelne if m[0] <= 20])
    con = db.open_db(path)
    assert db._user_version(con) == 20 and "image_count" not in _kolumny(con, "location")
    monkeypatch.setattr(db, "MIGRATIONS", pelne)
    prawdziwy = db._migration_sql

    def _z_awaria(filename):
        sql = prawdziwy(filename)
        if filename.startswith("0021"):
            sql += ("\nPRAGMA user_version = 21;" if wersja_w_tresci else "") + "\nSELECT brak_funkcji();"
        return sql
    monkeypatch.setattr(db, "_migration_sql", _z_awaria)
    with pytest.raises(Exception, match="brak_funkcji"):
        db.migrate(con)
    assert not con.in_transaction
    assert db._user_version(con) == 20
    assert "image_count" not in _kolumny(con, "location")
    con.close()
    monkeypatch.setattr(db, "_migration_sql", prawdziwy)
    con = db.open_db(path)
    assert db._user_version(con) == db.SCHEMA_VERSION
    assert "image_count" in _kolumny(con, "location")
    con.close()


def test_foreign_keys_on(tmp_path):
    con = db.connect(str(tmp_path / "h.db"))
    assert con.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    con.close()


def test_polaczenie_ma_synchronous_full(tmp_path):
    """Warunek 5 astry: backup nagłówka i faza zapisu w miejscu muszą przetrwać utratę zasilania
    zaraz po commicie - w WAL tylko FULL synchronizuje commit na dysk. Ustawione jawnie w `connect`,
    nie zostawione domyślnej wartości kompilacji SQLite."""
    con = db.connect(str(tmp_path / "s.db"))
    assert con.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert con.execute("PRAGMA synchronous").fetchone()[0] == 2        # 2 = FULL
    con.close()
