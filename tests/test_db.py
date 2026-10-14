"""Połączenie + runner migracji (user_version, idempotencja, FK, jawny błąd dla bazy v1)."""
import hashlib
import sqlite3

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
    # + 0023 inplace_op.anchor_sha1 + pending_changes.inplace_op_id (kotwica operacji, wiązanie)
    # + 0024 header_backups.unreplaced_at (backup bez podmiany - cofnięcie go pomija, AR-37)
    # + 0025 location.hdr_rule (wersja reguły koercji faktów kopii, AR-33)
    # + 0026 stack_version_kept + integration.creation_time (werdykt wersji stosów, AR-10)
    # + 0027 frame.observatory_source (stanowisko wskazane ręką)
    # + 0028 frame.channel (kanał R/G/B z nazwy stosu, P4-3)
    # + 0029 pending_renames.in_flight (trwały zamiar renamu przed mutacją, AR-29)
    # + 0030 header_backups.pending_since (backup niepotwierdzony, rekoncyliacja z dyskiem, AR-40)
    # + 0031 camera.pixel_source (piksel matrycy wpisany ręką, AR-55)
    # + 0032 frame_note (uwagi klatki, tylko w bazie, WO-2)
    # + 0033 integration_input.asserted_by z rangą `harvest` (zbiór dokładny z żniw, AR-102)
    # + 0034 stack_history + light_name_alias + podstawa rodowodu na integration
    # + 0035 stack_variant (wariant kadru stosu powiązany z oryginałem, AR-54)
    # + 0036 object_change_run + pending_object_change + run_dir (zmiana obiektu z plikiem, AR-17)
    # + 0037 withheld_write + pending_changes.withheld_id + header_backups.hand_version (AR-82)
    # + 0038 replace_intent (zamiar podmiany drogi atomowej, AR-64)
    # + 0039 telescope.focal_user + f_ratio_user (optyka teleskopu z ręki, AR-128)
    # + 0040 nagrobek object/telescope.retired_at + ślady gestów (cofnięcie zdejmuje, AR-133/AR-137)
    assert db._user_version(con) == db.SCHEMA_VERSION == 40
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


def _baza_z_nowszego_horreum(path):
    """Pełna baza tego kodu z numerem o jeden WYŻSZYM - tak wygląda baza po migracji, której
    ten program jeszcze nie zna (AR-69)."""
    con = db.open_db(path)
    con.execute(f"PRAGMA user_version = {db.SCHEMA_VERSION + 1}")
    con.close()


def test_baza_z_nowszego_horreum_odmowa_przed_migracja(tmp_path):
    """AR-69: dawniej `migrate` odmawiał tylko wersji spoza łańcucha NIŻSZEJ od własnej, więc
    wydanie v30 otwierało bazę v31 bez słowa. Odmowa pada, zanim cokolwiek się zmieni: numer
    i schemat zostają takie, jakie zapisał nowszy program.
    Falsyfikator: zdejmij warunek `current > SCHEMA_VERSION` → `migrate` przejdzie bez błędu."""
    path = str(tmp_path / "nowsza.db")
    _baza_z_nowszego_horreum(path)
    con = db.connect(path)
    schemat = con.execute("SELECT type, name, sql FROM sqlite_master ORDER BY name").fetchall()
    with pytest.raises(db.SchemaTooNew, match="zaktualizuj Horreum") as odmowa:
        db.migrate(con)
    assert odmowa.value.found == db.SCHEMA_VERSION + 1
    assert db._user_version(con) == db.SCHEMA_VERSION + 1
    assert con.execute("SELECT type, name, sql FROM sqlite_master ORDER BY name").fetchall() \
        == schemat
    con.close()


def test_open_db_zamyka_polaczenie_przy_odmowie_i_nie_rusza_pliku(tmp_path):
    """Odmowa w `open_db` nie zostawia otwartego uchwytu: okno GUI łapie wyjątek i nie ma czego
    zamknąć, a na Windows otwarte połączenie trzyma plik bazy. Dowód z dysku: plik da się
    przenieść zaraz po odmowie. Falsyfikator: zdejmij `con.close()` z `open_db` → `PermissionError`
    na Windows.

    Druga połowa dowodu to zdanie „baza zostaje nietknięta” z komunikatu: `connect` ustawia
    `journal_mode = WAL`, ale baza Horreum jest w WAL od pierwszego otwarcia, więc PRAGMA niczego
    nie zapisuje - plik ma po odmowie ten sam odcisk co do bajtu (bramka `kimi` Z1, sesja bu)."""
    path = tmp_path / "nowsza.db"
    _baza_z_nowszego_horreum(str(path))
    przed = hashlib.sha1(path.read_bytes()).hexdigest()
    with pytest.raises(db.SchemaTooNew):
        db.open_db(str(path))
    assert hashlib.sha1(path.read_bytes()).hexdigest() == przed
    path.rename(tmp_path / "przeniesiona.db")


@pytest.mark.parametrize("rodzaj", ["smieci", "obcieta"])
def test_open_db_plik_ktory_nie_jest_baza_nie_trzyma_uchwytu(tmp_path, rodzaj):
    """AR-124: plik-śmieć i obcięta kopia przechodzą `sqlite3.connect`, a padają dopiero na
    `journal_mode` w `connect` - poza obwódką migracji w `open_db`. Porzucone połączenie żyje
    w cyklu z własną pamięcią podręczną instrukcji, więc bez `close()` trzyma plik do przebiegu
    GC. Dowód z dysku: przeniesienie zaraz po błędzie, bez `gc.collect()`.
    Falsyfikator: zdejmij `con.close()` z `except` w `connect` → `PermissionError` na Windows."""
    path = tmp_path / f"{rodzaj}.db"
    if rodzaj == "smieci":
        path.write_bytes(b"to nie jest baza Horreum" * 200)
    else:
        zrodlo = tmp_path / "zrodlo.db"
        db.open_db(str(zrodlo)).close()
        dane = zrodlo.read_bytes()
        path.write_bytes(dane[: len(dane) // 3])
    with pytest.raises(sqlite3.DatabaseError):
        db.open_db(str(path))
    path.rename(tmp_path / "przeniesiona.db")


@pytest.mark.parametrize("komenda", [["init", "{db}"], ["human-facts", "{db}"], ["plan", "{db}"]])
def test_cli_odmawia_bazy_z_nowszego_horreum_zdaniem_i_kodem_2(tmp_path, capsys, komenda):
    """CLI mówi odmowę jednym zdaniem i kodem 2, nie śladem stosu - także w komendach, które
    czytają bez migracji (`plan` radził dotąd `horreum init`, a `human-facts` liczył fakty ręki
    bazy, której schematu nie zna)."""
    from horreum import cli

    path = str(tmp_path / "nowsza.db")
    _baza_z_nowszego_horreum(path)
    assert cli.main([a.format(db=path) for a in komenda]) == 2
    out = capsys.readouterr().out
    assert "ODMOWA" in out and f"v{db.SCHEMA_VERSION + 1}" in out and "zaktualizuj Horreum" in out
    assert "init" not in out


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
