"""Schemat 0002 + 0003 — tabele/widoki istnieją, kształt zgodny z briefem przejścia §8
i briefem writebacku §2 (staging krok 4)."""
import json
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
    # 0011 — kuratela celów planera (T4)
    "target_plan",
    # 0022 - dziennik zapisu w miejscu (O5/Q8)
    "inplace_op",
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
    """Świeża baza startuje z PUSTYMI tabelami rodowodu — populację robi dopiero przebieg.

    Wcześniejsze uzasadnienie („nie projektujemy pod dane, których nie ma") STRACIŁO WAŻNOŚĆ
    2026-08-02: `calibration` ma pisarza od C4, `integration`/`integration_input` od I-2c, a 0012
    dołożyło im kontrakt. Test zostaje w innej roli — pilnuje, że sama MIGRACJA niczego nie
    wstawia (backfill „na oko" byłby zgadywaniem rodowodu, którego nikt nie zmierzył)."""
    con = db.open_db(str(tmp_path / "h.db"))
    for t in ("calibration", "integration", "integration_input"):
        assert con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] == 0
    con.close()


def test_user_version_v26_po_migracji(tmp_path):
    """0026 podnosi user_version do 26 (świeża baza leci 0002→…→0026 sekwencyjnie; 0025 = wersja
    reguły koercji faktów kopii `location.hdr_rule`, AR-33; 0026 = werdykt „zostaw wszystkie
    wersje” `stack_version_kept` + `integration.creation_time`, AR-10).

    Pin JEST intencją: każda nowa migracja ma ten test PRZEWRÓCIĆ imiennie, żeby podniesienie
    wersji było gestem, a nie skutkiem ubocznym."""
    con = db.open_db(str(tmp_path / "h.db"))
    assert con.execute("PRAGMA user_version").fetchone()[0] == 26
    assert db.SCHEMA_VERSION == 26
    con.close()


def _baza_v24_z_kopiami(path):
    """Baza v24 (migracje do 0024 włącznie) z dwiema kopiami: lid 1 z zebranymi faktami (kotwica
    = odcisk), lid 2 bez faktów - stan żywego archiwum tuż przed 0025."""
    con = db.connect(path)
    for version, filename in db.MIGRATIONS:
        if version <= 24:
            con.executescript(db._migration_sql(filename))
            con.execute(f"PRAGMA user_version = {int(version)}")
    _loc_0021(con, 1)
    _loc_0021(con, 2)
    con.execute("UPDATE location SET hdr_hash = 'hh', hdr_filter = 'Ha', hdr_exptime = 1.5 "
                "WHERE id = 1")
    con.commit()
    return con


def test_0025_przyrost_na_bazie_v24_stempluje_zebrane_fakty(tmp_path):
    """Baza v24 przechodzi 0025: kopia z zebranymi faktami dostaje `hdr_rule = 1` (jedyna reguła
    od 0021 - stempel jest odczytem prawdy, więc migracja NIE wysyła zebranych kopii do ponownego
    czytania), kopia bez faktów zostaje NULL (dalej kandydat uzupełnienia). Fakty nietknięte,
    druga migracja to no-op.

    Falsyfikator: zdejmij `UPDATE` z 0025 → lid 1 ma NULL i wraca na listę kandydatów."""
    con = _baza_v24_z_kopiami(str(tmp_path / "v24.db"))
    assert db.migrate(con) == db.SCHEMA_VERSION
    wiersze = [tuple(r) for r in con.execute(
        "SELECT id, hdr_hash, hdr_filter, hdr_exptime, hdr_rule FROM location ORDER BY id")]
    assert wiersze == [(1, "hh", "Ha", 1.5, 1), (2, None, None, None, None)]
    assert db.migrate(con) == db.SCHEMA_VERSION              # idempotencja
    con.close()


def test_0025_CHECK_regula_przy_kotwicy_i_liczbowa(tmp_path):
    """STRAŻNIK W DDL (0025): reguła bez kotwicy faktów to sprzeczność; reguła jest liczbą całkowitą
    >= 1. Kotwica BEZ reguły zostaje legalna (stan „reguła nieznana", który dobiera sterownik).
    Kolumna wchodzi przez `ADD COLUMN`, więc test dowodzi, że SQLite egzekwuje CHECK.

    Falsyfikator: zdejmij `CHECK` z `0025_location_hdr_rule.sql` → pierwszy `raises` czerwienieje."""
    con = _baza_v24_z_kopiami(str(tmp_path / "v24.db"))
    db.migrate(con)
    with pytest.raises(sqlite3.IntegrityError):              # reguła bez kotwicy
        con.execute("UPDATE location SET hdr_rule = 1 WHERE id = 2")
    with pytest.raises(sqlite3.IntegrityError):              # tekst zamiast numeru
        con.execute("UPDATE location SET hdr_rule = 'jeden' WHERE id = 1")
    with pytest.raises(sqlite3.IntegrityError):              # ułamek zamiast numeru
        con.execute("UPDATE location SET hdr_rule = 1.5 WHERE id = 1")
    with pytest.raises(sqlite3.IntegrityError):              # numer spoza łańcucha reguł
        con.execute("UPDATE location SET hdr_rule = 0 WHERE id = 1")
    with pytest.raises(sqlite3.IntegrityError):              # zdjęcie kotwicy przy stojącej regule
        con.execute("UPDATE location SET hdr_hash = NULL, hdr_filter = NULL, hdr_exptime = NULL "
                    "WHERE id = 1")
    con.execute("UPDATE location SET hdr_rule = NULL WHERE id = 1")      # reguła nieznana - legalna
    con.execute("UPDATE location SET hdr_rule = 2 WHERE id = 1")
    con.close()


def test_0024_przyrost_na_bazie_v23_z_backupem(tmp_path):
    """Baza v23 z backupem commitu przechodzi 0024: kolumna `unreplaced_at` wchodzi PUSTA (NULL =
    cofnięcie jak dotąd - backfillu nie ma, SQL nie wie, który backup poprzedził podmianę), wiersz
    zostaje nietknięty, a druga migracja to no-op.

    Falsyfikator: dopisz do 0024 `DEFAULT`/backfill → istniejący backup dostaje znacznik
    i cofnięcie starego commitu by go pominęło."""
    path = str(tmp_path / "v23.db")
    con = db.connect(path)
    for version, filename in db.MIGRATIONS:
        if version <= 23:
            con.executescript(db._migration_sql(filename))
            con.execute(f"PRAGMA user_version = {int(version)}")
    _loc_0021(con, 1)
    con.execute("INSERT INTO commits(id, run_id, applied_at) VALUES (1, 'R', 't')")
    con.execute("INSERT INTO header_backups(commit_id, location_id, hdu_index, header_text, "
                "post_hash) VALUES (1, 1, NULL, 'xml', 'ph')")
    con.commit()
    assert db.migrate(con) == db.SCHEMA_VERSION              # 0024 + każda kolejna
    row = con.execute("SELECT commit_id, location_id, header_text, post_hash, unreplaced_at "
                      "FROM header_backups").fetchone()
    assert tuple(row) == (1, 1, "xml", "ph", None)
    assert db.migrate(con) == db.SCHEMA_VERSION              # idempotencja
    con.close()


def _loc_0021(con, lid, header_hash="hh"):
    """Klatka + kopia z zadanym odciskiem nagłówka - surowy INSERT, bo test pyta BAZĘ, nie klingę."""
    con.execute("INSERT INTO frame(id, kind, filetype, sha1_data, first_seen_at) "
                "VALUES (?, 'master_flat', 'xisf', ?, '2026-09-26T00:00:00Z')", (lid, f"s{lid}"))
    con.execute("INSERT INTO location(id, frame_id, volume, path, header_hash) "
                "VALUES (?, ?, 'V', ?, ?)", (lid, lid, f"/a/{lid}.xisf", header_hash))


def test_0021_CHECK_kotwica_i_para_obrazow(tmp_path):
    """STRAŻNIKI W DDL (0021): fakty kopii opisują nagłówek o odcisku `hdr_hash`, więc
      * kotwica różna od `header_hash` wiersza jest sprzecznością - pisarz, który zmieni odcisk
        kopii i nie odświeży jej faktów, dostaje IntegrityError zamiast cichej nieprawdy;
      * fakt bez kotwicy jest sprzecznością (wzorzec 0019);
      * liczba obrazów i lista ról występują RAZEM, a długość listy = liczba;
      * pola liczbowe nie przyjmą tekstu (ostatnia bramka W3).
    Kolumny wchodzą przez `ADD COLUMN`, więc test dowodzi, że SQLite realnie egzekwuje te CHECK-i.

    Falsyfikator: zdejmij którykolwiek `CHECK` z `0021_location_copy_facts.sql` → odpowiadający mu
    `raises` czerwienieje."""
    con = db.open_db(str(tmp_path / "h.db"))
    _loc_0021(con, 1)
    _loc_0021(con, 2, header_hash=None)
    with pytest.raises(sqlite3.IntegrityError):              # kotwica cudzego nagłówka
        con.execute("UPDATE location SET hdr_hash = 'inny' WHERE id = 1")
    with pytest.raises(sqlite3.IntegrityError):              # fakt bez kotwicy
        con.execute("UPDATE location SET hdr_filter = 'Ha' WHERE id = 1")
    with pytest.raises(sqlite3.IntegrityError):              # liczba bez listy
        con.execute("UPDATE location SET hdr_hash = 'hh', image_count = 2 WHERE id = 1")
    with pytest.raises(sqlite3.IntegrityError):              # lista krótsza niż liczba
        con.execute("UPDATE location SET hdr_hash = 'hh', image_count = 2, "
                    "image_roles = '[\"integration\"]' WHERE id = 1")
    with pytest.raises(sqlite3.IntegrityError):              # lista, która nie jest tablicą
        con.execute("UPDATE location SET hdr_hash = 'hh', image_count = 1, "
                    "image_roles = '\"integration\"' WHERE id = 1")
    with pytest.raises(sqlite3.IntegrityError):              # tekst w polu liczbowym
        con.execute("UPDATE location SET hdr_hash = 'hh', hdr_exptime = 'abc' WHERE id = 1")
    with pytest.raises(sqlite3.IntegrityError):              # kotwica przy kopii bez odcisku
        con.execute("UPDATE location SET hdr_hash = 'hh' WHERE id = 2")
    con.execute("UPDATE location SET hdr_hash = 'hh', image_count = 2, "
                "image_roles = '[\"integration\", null]', hdr_filter = 'Ha', hdr_exptime = 1.5, "
                "hdr_xbinning = 1 WHERE id = 1")             # komplet z kotwicą - legalny
    with pytest.raises(sqlite3.IntegrityError):              # odcisk zmieniony BEZ faktów
        con.execute("UPDATE location SET header_hash = 'nowy' WHERE id = 1")
    con.execute("UPDATE location SET header_hash = 'nowy', hdr_hash = 'nowy' WHERE id = 1")
    con.close()


def test_0021_przyrost_na_bazie_v20_z_kopia(tmp_path):
    """Baza v20 z kopią o znanym odcisku przechodzi 0021 bez odmowy (CHECK-i testowane na
    istniejących wierszach - nowe kolumny wchodzą PUSTE), wiersz zostaje nietknięty, a druga
    migracja to no-op. Backfillu w migracji nie ma: fakty są w pliku, SQL ich nie zna.

    Falsyfikator: dopisz do 0021 `NOT NULL`/`DEFAULT` → migracja wybucha albo kolumna przestaje być NULL."""
    path = str(tmp_path / "v20.db")
    con = db.connect(path)
    for version, filename in db.MIGRATIONS:
        if version <= 20:
            con.executescript(db._migration_sql(filename))
            con.execute(f"PRAGMA user_version = {int(version)}")
    _loc_0021(con, 1)
    con.commit()
    assert db.migrate(con) == db.SCHEMA_VERSION              # 0021 + każda kolejna
    row = con.execute("SELECT header_hash, image_count, image_roles, hdr_filter, hdr_hash "
                      "FROM location WHERE id = 1").fetchone()
    assert tuple(row) == ("hh", None, None, None, None)
    assert db.migrate(con) == db.SCHEMA_VERSION              # idempotencja
    con.close()


def _integ_0020(con, iid, reason):
    """Klatka mastera + głowa integracji z zadanym werdyktem - surowy INSERT, bo test pyta BAZĘ."""
    con.execute("INSERT INTO frame(id, kind, filetype, sha1_data, first_seen_at) "
                "VALUES (?, 'master_light', 'xisf', ?, '2026-09-26T00:00:00Z')", (iid, f"m{iid}"))
    con.execute("INSERT INTO integration(id, master_frame_id, created_at, unresolved_reason) "
                "VALUES (?, ?, 't', ?)", (iid, iid, reason))


def test_0020_CHECK_uwaga_dodatnia_i_nie_dubluje_werdyktu(tmp_path):
    """STRAŻNIK W DDL (G2-1d): uwaga `raw_unreferenced` ma JEDNĄ postać braku (NULL, nie zero)
    i nie stoi obok werdyktu `offset_unknown`, który mówi to samo. Przy rodowodzie (werdykt NULL)
    i przy INNYM werdykcie jest legalna - to cała jej treść: pula mieszana RAW+FITS mówi wtedy
    o RAW-ach, których nie umie umieścić w czasie.

    Falsyfikator: zdejmij którykolwiek `CHECK` z `0020_integration_raw_unreferenced.sql` →
    odpowiadający mu `raises` czerwienieje."""
    con = db.open_db(str(tmp_path / "h.db"))
    _integ_0020(con, 1, None)                                # rodowód bez powodu
    _integ_0020(con, 2, "offset_unknown")
    _integ_0020(con, 3, "telescope_mismatch")
    with pytest.raises(sqlite3.IntegrityError):              # zero to nie uwaga
        con.execute("UPDATE integration SET raw_unreferenced = 0 WHERE id = 1")
    with pytest.raises(sqlite3.IntegrityError):              # dubel werdyktu
        con.execute("UPDATE integration SET raw_unreferenced = 3 WHERE id = 2")
    con.execute("UPDATE integration SET raw_unreferenced = 3 WHERE id = 1")   # obok rodowodu
    con.execute("UPDATE integration SET raw_unreferenced = 2 WHERE id = 3")   # obok innego powodu
    with pytest.raises(sqlite3.IntegrityError):              # werdykt nie przeskoczy na dubel
        con.execute("UPDATE integration SET unresolved_reason = 'offset_unknown' WHERE id = 3")
    con.close()


def test_0020_przyrost_na_bazie_v19_z_integracja(tmp_path):
    """Baza v19 z gotową integracją przechodzi 0020 bez odmowy (kolumna wchodzi PUSTA, bez
    backfillu - liczbę ustawia najbliższy przebieg), wiersz zostaje nietknięty, a druga migracja
    to no-op.

    Falsyfikator: dopisz do 0020 `NOT NULL`/`DEFAULT 0` → migracja wybucha albo kolumna przestaje
    być NULL."""
    path = str(tmp_path / "v19.db")
    con = db.connect(path)
    for version, filename in db.MIGRATIONS:
        if version <= 19:
            con.executescript(db._migration_sql(filename))
            con.execute(f"PRAGMA user_version = {int(version)}")
    _integ_0020(con, 1, "offset_unknown")
    con.commit()
    assert db.migrate(con) == db.SCHEMA_VERSION              # 0020 + każda kolejna
    row = con.execute("SELECT unresolved_reason, raw_unreferenced FROM integration "
                      "WHERE id = 1").fetchone()
    assert tuple(row) == ("offset_unknown", None)
    assert db.migrate(con) == db.SCHEMA_VERSION              # idempotencja
    con.close()


def _loc_0019(con, lid, since):
    """Klatka + kopia z zadanym markerem - surowy INSERT, bo test pyta BAZĘ, nie klingę."""
    con.execute("INSERT INTO frame(id, kind, filetype, sha1_data, first_seen_at) "
                "VALUES (?, 'light', 'fits', ?, '2026-09-26T00:00:00Z')", (lid, f"sha{lid}"))
    con.execute("INSERT INTO location(id, frame_id, volume, path, unreadable_since) "
                "VALUES (?, ?, 'V', ?, ?)", (lid, lid, f"/a/{lid}.fits", since))


def test_0019_CHECK_rodzaj_i_powod_tylko_przy_markerze(tmp_path):
    """STRAŻNIK W DDL (P4-2): rodzaj spoza słownika ('io'|'parse'|'db') i rodzaj/powód BEZ markera to
    sprzeczność, którą baza odbija - pisarz, który zgasi marker i zapomni zdjąć diagnozę, nie
    zostawi jej przy zdrowej kopii. Kolumny wchodzą przez `ADD COLUMN`, więc test dowodzi, że SQLite
    realnie egzekwuje oba CHECK-i dołożone tą drogą. Trzecia wartość słownika, `'db'` (błąd bazy
    po naszej stronie), przechodzi - pisze ją backstop skanu.

    Kierunek odwrotny (marker BEZ rodzaju) zostaje legalny: rodzaj nieznany - wiersz sprzed 0019
    nie ma skąd go wziąć, a goły `OSError` bez dowodu bajtów zostaje nierozstrzygnięty.

    Falsyfikator: zdejmij którykolwiek `CHECK` z `0019_location_unreadable_reason.sql` → odpowiadający
    mu `raises` czerwienieje; zdejmij `'db'` ze słownika w CHECK → zapis `'db'` rzuca
    `IntegrityError`."""
    con = db.open_db(str(tmp_path / "h.db"))
    _loc_0019(con, 1, None)                                  # kopia czytelna
    _loc_0019(con, 2, "2026-09-26T10:00:00")                 # kopia oznaczona
    with pytest.raises(sqlite3.IntegrityError):              # rodzaj bez markera
        con.execute("UPDATE location SET unreadable_kind = 'io' WHERE id = 1")
    with pytest.raises(sqlite3.IntegrityError):              # powód bez markera
        con.execute("UPDATE location SET unreadable_reason = 'OSError: x' WHERE id = 1")
    with pytest.raises(sqlite3.IntegrityError):              # rodzaj spoza słownika
        con.execute("UPDATE location SET unreadable_kind = 'xyz' WHERE id = 2")
    with pytest.raises(sqlite3.IntegrityError):              # zgaszenie SAMEGO markera
        con.execute("UPDATE location SET unreadable_kind = 'parse' WHERE id = 2")
        con.execute("UPDATE location SET unreadable_since = NULL WHERE id = 2")
    con.execute("UPDATE location SET unreadable_kind = 'parse', unreadable_reason = 'ParseError: x' "
                "WHERE id = 2")                              # przy markerze - legalne
    con.execute("UPDATE location SET unreadable_kind = 'db', "
                "unreadable_reason = 'OperationalError: database is locked' "
                "WHERE id = 2")                              # trzecia wartość słownika - legalna
    con.execute("UPDATE location SET unreadable_since = NULL, unreadable_kind = NULL, "
                "unreadable_reason = NULL WHERE id = 2")    # gaśnie RAZEM - legalne
    _loc_0019(con, 3, "2026-09-26T11:00:00")                 # marker bez rodzaju - legalny
    con.close()


def test_0019_przyrost_na_bazie_v18_z_oznaczona_kopia(tmp_path):
    """Baza v18 z kopią JUŻ oznaczoną przechodzi 0019 bez odmowy (CHECK nie odbija istniejących
    wierszy - nowe kolumny wchodzą PUSTE), wiersz zostaje nietknięty, a druga migracja to no-op.
    Backfillu nie ma: rodzaj takiej kopii pojawi się dopiero przy re-odczycie.

    Falsyfikator: dopisz do 0019 `NOT NULL` albo backfill z tekstu → `migrate` wybucha na tym
    wierszu albo kolumna przestaje być NULL."""
    path = str(tmp_path / "v18.db")
    con = db.connect(path)
    for version, filename in db.MIGRATIONS:
        if version <= 18:
            con.executescript(db._migration_sql(filename))
            con.execute(f"PRAGMA user_version = {int(version)}")
    _loc_0019(con, 1, "2026-07-21T12:00:00")
    con.commit()
    assert db.migrate(con) == db.SCHEMA_VERSION              # 0019 + każda kolejna
    row = con.execute("SELECT unreadable_since, unreadable_kind, unreadable_reason FROM location "
                      "WHERE id = 1").fetchone()
    assert tuple(row) == ("2026-07-21T12:00:00", None, None)
    assert db.migrate(con) == db.SCHEMA_VERSION              # idempotencja
    con.close()


def test_0017_CHECK_odbija_pamiec_bez_nagrobka(tmp_path):
    """STRAŻNIK W DDL, nie konwencja: pamięć nagrobka (`object_cleared_id`) wolno nieść WYŁĄCZNIE
    klatce, która jest nagrobkiem (`object_source='user_cleared'`).

    Bez tego CHECK-a pisarz, który przypisze obiekt klatce cofniętej i zapomni zdjąć pamięć,
    zostawiłby wskazanie na obiekt, którego ta klatka już nie odrzuca — a każdy czytelnik pamięci
    (gest przywracania) wziąłby je za żywy werdykt. Kolumna wchodzi przez `ADD COLUMN`, więc test
    dowodzi, że SQLite realnie egzekwuje CHECK dołożony tą drogą, a nie tylko go zapamiętuje.

    Falsyfikator: zdejmij `CHECK` z `0017_object_cleared_memory.sql` → oba `raises` czerwienieją."""
    con = db.open_db(str(tmp_path / "h.db"))
    con.execute("INSERT INTO object(id, canon) VALUES (5, 'LMC')")
    con.execute("INSERT INTO frame(id, kind, filetype, sha1_data, first_seen_at, object_id, "
                "object_source, object_cleared_id) "
                "VALUES (1, 'light', 'fits', 'sha1', '2026-08-10T00:00:00Z', NULL, "
                "'user_cleared', 5)")                       # nagrobek Z pamięcią — legalny
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO frame(id, kind, filetype, sha1_data, first_seen_at, object_id, "
                    "object_source, object_cleared_id) "
                    "VALUES (2, 'light', 'fits', 'sha2', '2026-08-10T00:00:00Z', 5, 'user', 5)")
    with pytest.raises(sqlite3.IntegrityError):             # …i tą samą drogą, którą idzie klinga
        con.execute("UPDATE frame SET object_id = 5, object_source = 'user' WHERE id = 1")
    # NAGROBEK BEZ PAMIĘCI ZOSTAJE LEGALNY — baza-dawca przywozi nagrobki sprzed tej migracji,
    # a odmowa ich wpuszczenia byłaby utratą werdyktu ręki.
    con.execute("INSERT INTO frame(id, kind, filetype, sha1_data, first_seen_at, object_id, "
                "object_source) "
                "VALUES (3, 'light', 'fits', 'sha3', '2026-08-10T00:00:00Z', NULL, 'user_cleared')")
    con.close()


def test_0013_saved_query_rebuild_kontrakt(tmp_path):
    """0013 (I-1): PRZEBUDOWA `saved_query` — `sql_text` → `spec_json` + `updated_at`.

    Test wchodzi na bazę Z WIERSZEM szkieletu, bo tylko tak widać obie połowy decyzji: treść
    PRZEŻYWA (nic nie kasujemy), ale trafia pod znacznik `legacy_sql`, więc czytelnik rozpozna ją
    jako NIE-specyfikację. Skopiowanie SQL-a wprost do `spec_json` byłoby gorsze niż strata: spec
    bez znanych kluczy czyta się w gridzie jak perspektywa PUSTA, czyli filtr zdejmujący filtr."""
    path = str(tmp_path / "h.db")
    con = db.connect(path)
    # Migracje DO v12 WŁĄCZNIE, pinowane LICZBĄ — nie `MIGRATIONS[:-1]`. Indeks względem końca
    # listy znaczy „wszystko poza ostatnią", więc każda NOWA migracja przesuwała ten test o jedną
    # pozycję i wpuszczała 0013, które testowaną kolumnę już usuwa. Przewróciła go dopiero 0014,
    # choć zepsuty był od chwili napisania (docs.md: wartość zmienna w czasie — pin albo derywacja).
    for v, _f in [m for m in db.MIGRATIONS if m[0] <= 12]:
        con.executescript(db._migration_sql(dict(db.MIGRATIONS)[v]))
    con.execute("PRAGMA user_version = 12")
    con.execute("INSERT INTO saved_query(id, name, sql_text, created_at) "
                "VALUES (3, 'stary', 'SELECT 1', 't')")
    con.commit()

    con = db.open_db(path)                                       # v12 → dziś (0013 przebudowuje)
    assert con.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    row = con.execute("SELECT id, name, spec_json, updated_at FROM saved_query").fetchone()
    assert (row["id"], row["name"], row["updated_at"]) == (3, "stary", None)
    assert json.loads(row["spec_json"]) == {"legacy_sql": "SELECT 1"}
    cols = {r[1] for r in con.execute("PRAGMA table_info(saved_query)")}
    assert "sql_text" not in cols and {"spec_json", "updated_at"} <= cols
    assert "name" in _unique_cols(con, "saved_query")
    with pytest.raises(sqlite3.IntegrityError):                  # nazwa JEST tożsamością
        con.execute("INSERT INTO saved_query(name, spec_json, created_at) "
                    "VALUES ('stary', '{}', 't')")
    con.close()


def test_0012_integration_rebuild_kontrakt(tmp_path):
    """0012 (I-2c): PRZEBUDOWA obu tabel rodowodu stosów. `integration` dostaje tożsamość na KLATCE
    MASTERA (UNIQUE + NOT NULL), `integration_input` — UNIQUE(integracja, wejście) jako strażnik
    idempotencji i CHECK na trójstanie `asserted_by`. Test wchodzi na bazę Z DANYMI szkieletu,
    by dowieść, że INSERT SELECT nie gubi wierszy, a stary wiersz relacji dostaje `window`
    (najsłabsze źródło — awans wymaga dowodu, nie migracji)."""
    path = str(tmp_path / "h.db")
    con = db.connect(path)
    for v in ("0002_initial.sql", "0003_writeback.sql", "0004_observatory.sql", "0005_rename.sql",
              "0006_unreadable.sql", "0007_backup_hdu_nullable.sql", "0008_calibration.sql",
              "0009_calibration_lineage.sql", "0010_kind_source.sql", "0011_target_plan.sql"):
        con.executescript(db._migration_sql(v))
    con.execute("PRAGMA user_version = 11")
    con.execute("INSERT INTO frame(id, sha1_data, kind, filetype, first_seen_at) "
                "VALUES (1, 'm1', 'master_light', 'xisf', 't'), (2, 'l1', 'light', 'fits', 't')")
    con.execute("INSERT INTO integration(id, master_frame_id, integ_hash, created_at, tool) "
                "VALUES (7, 1, 'h', 't', 'WBPP')")
    con.execute("INSERT INTO integration_input(integration_id, input_frame_id) VALUES (7, 2)")
    con.commit()

    con = db.open_db(path)                                       # v11 → v12 (przebudowa)
    assert con.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    row = con.execute("SELECT id, master_frame_id, integ_hash, tool FROM integration").fetchone()
    assert tuple(row) == (7, 1, "h", "WBPP")                     # wiersz przeżył Z id-em
    assert con.execute("SELECT asserted_by FROM integration_input").fetchone()[0] == "window"

    assert _unique_cols(con, "integration") >= {"master_frame_id"}
    with pytest.raises(sqlite3.IntegrityError):                  # drugi wiersz o tym samym masterze
        con.execute("INSERT INTO integration(master_frame_id, created_at) VALUES (1, 't')")
    with pytest.raises(sqlite3.IntegrityError):                  # duplikat relacji
        con.execute("INSERT INTO integration_input(integration_id, input_frame_id, asserted_by) "
                    "VALUES (7, 2, 'history')")
    with pytest.raises(sqlite3.IntegrityError):                  # CHECK asserted_by
        con.execute("INSERT INTO integration_input(integration_id, input_frame_id, asserted_by) "
                    "VALUES (7, 1, 'zgadywanie')")
    with pytest.raises(sqlite3.IntegrityError):                  # CHECK unresolved_reason
        con.execute("INSERT INTO integration(master_frame_id, created_at, unresolved_reason) "
                    "VALUES (2, 't', 'bo tak')")
    con.close()


def test_0016_integration_rebuild_nie_gubi_rodowodu(tmp_path):
    """0016 (#DR2/R2): PRZEBUDOWA `integration` pod nową kolumnę `utc_offset_min` i token
    `offset_unknown` w CHECK-u powodów.

    TO JEST PIERWSZA PRZEBUDOWA TABELI Z REALNYMI DANYMI w tym repo i cały ciężar testu leży
    właśnie tam. 0012 i 0009 przebudowywały PUSTY szkielet, więc ich `INSERT SELECT` mógł kopiować
    podzbiór kolumn i wstawiać stałą `'window'` do dziecka — kopiował zero wierszy. Tu na żywej
    bazie stoi 128 integracji i 3367 wejść, więc pominięta kolumna nie jest niechlujstwem, tylko
    CICHĄ UTRATĄ rodowodu gotowych obrazów. Dlatego wiersze wchodzą tu z KOMPLETEM faktów, w tym
    dwoma, które stałą-w-migracji zamalowałaby bez śladu: `asserted_by='history'` (zeznanie pliku,
    mocniejsze od okna) i `excluded=1` (werdykt CZŁOWIEKA — jego „nie" jest faktem)."""
    path = str(tmp_path / "h.db")
    con = db.connect(path)
    for v, _f in [m for m in db.MIGRATIONS if m[0] <= 15]:
        con.executescript(db._migration_sql(dict(db.MIGRATIONS)[v]))
    con.execute("PRAGMA user_version = 15")
    con.execute("INSERT INTO frame(id, sha1_data, kind, filetype, first_seen_at) "
                "VALUES (1, 'm1', 'master_light', 'xisf', 't'), (2, 'l1', 'light', 'raw', 't'), "
                "(3, 'l2', 'light', 'raw', 't'), (4, 'm2', 'master_light', 'xisf', 't')")
    con.execute(
        "INSERT INTO integration(id, master_frame_id, integ_hash, created_at, updated_at, tool, "
        "window_start, window_end, declared_rows, drizzle_inputs, disabled_inputs, degenerate, "
        "ambiguous, telescope_mismatch, unresolved_reason) VALUES "
        "(7, 1, 'h7', 't0', 't1', 'WBPP', '2019-01-10T20:40:38', '2019-01-10T21:45:00', "
        " 3, 2, 1, 0, 1, 0, NULL), "
        "(8, 4, 'h8', 't0', NULL, NULL, NULL, NULL, NULL, NULL, NULL, 1, 0, 0, 'no_candidates')")
    con.execute("INSERT INTO integration_input(integration_id, input_frame_id, asserted_by, "
                "excluded) VALUES (7, 2, 'history', 0), (7, 3, 'user', 1)")
    con.commit()

    con = db.open_db(path)                                       # v15 → v16 (przebudowa)
    assert con.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION

    glowy = con.execute(
        "SELECT id, master_frame_id, integ_hash, created_at, updated_at, tool, window_start, "
        "window_end, declared_rows, drizzle_inputs, disabled_inputs, degenerate, ambiguous, "
        "telescope_mismatch, unresolved_reason, utc_offset_min FROM integration ORDER BY id"
    ).fetchall()
    assert [tuple(r) for r in glowy] == [
        (7, 1, "h7", "t0", "t1", "WBPP", "2019-01-10T20:40:38", "2019-01-10T21:45:00",
         3, 2, 1, 0, 1, 0, None, None),
        (8, 4, "h8", "t0", None, None, None, None, None, None, None, 1, 0, 0,
         "no_candidates", None)]

    wejscia = con.execute("SELECT integration_id, input_frame_id, asserted_by, excluded "
                          "FROM integration_input ORDER BY input_frame_id").fetchall()
    assert [tuple(r) for r in wejscia] == [(7, 2, "history", 0), (7, 3, "user", 1)]

    # Kontrakt tabeli przeżył przebudowę — inaczej migracja oddałaby dane bez strażników.
    assert _unique_cols(con, "integration") >= {"master_frame_id"}
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO integration(master_frame_id, created_at) VALUES (1, 't')")
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO integration_input(integration_id, input_frame_id, asserted_by) "
                    "VALUES (7, 2, 'window')")
    with pytest.raises(sqlite3.IntegrityError):                  # CHECK dalej odrzuca literówkę
        con.execute("INSERT INTO integration(master_frame_id, created_at, unresolved_reason) "
                    "VALUES (2, 't', 'bo tak')")
    con.execute("INSERT INTO integration(master_frame_id, created_at, unresolved_reason) "
                "VALUES (2, 't', 'offset_unknown')")             # …a NOWY token przepuszcza
    con.rollback()
    assert con.execute(
        "SELECT count(*) FROM sqlite_master WHERE type = 'index' "
        "AND name = 'idx_integration_input_frame'").fetchone()[0] == 1
    assert con.execute(
        "SELECT count(*) FROM sqlite_master WHERE name = '_integration_input_hold'"
    ).fetchone()[0] == 0, "przechowalnia FK ma zniknąć — inaczej zostaje sierocy stół w bazie"
    con.close()


def test_0009_calibration_rebuild_kontrakt(tmp_path):
    """0009 (C4): PRZEBUDOWA `calibration` — pusty szkielet 0002 dostaje NOT NULL + CHECK(relation)
    + UNIQUE(light_frame_id, relation). To ON trzyma idempotencję rodowodu (nie kod). Test wchodzi
    na bazę Z DANYMI (dwie klatki), by dowieść, że INSERT SELECT nie gubi wierszy i kontrakt działa."""
    path = str(tmp_path / "h.db")
    con = db.connect(path)
    con.executescript(db._migration_sql("0002_initial.sql"))
    for v in ("0003_writeback.sql", "0004_observatory.sql", "0005_rename.sql",
              "0006_unreadable.sql", "0007_backup_hdu_nullable.sql", "0008_calibration.sql"):
        con.executescript(db._migration_sql(v))
    con.execute("PRAGMA user_version = 8")
    # dwie klatki, by relacja miała na czym stanąć (FK ON)
    con.execute("INSERT INTO frame(id, sha1_data, kind, filetype, first_seen_at) "
                "VALUES (1, 'l1', 'light', 'fits', 't'), (2, 'm1', 'master_flat', 'fits', 't')")
    con.execute("INSERT INTO calibration(light_frame_id, master_frame_id, relation, asserted_by, "
                "confidence) VALUES (1, 2, 'flat', 'horreum', 'recipe')")
    con.commit()

    con = db.open_db(path)                                       # v8 → v9 (przebudowa)
    assert con.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    assert con.execute("SELECT count(*) FROM calibration").fetchone()[0] == 1   # wiersz przeżył

    uniq = _unique_cols(con, "calibration")
    assert {"light_frame_id", "relation"} <= uniq                # UNIQUE(light, relation)
    with pytest.raises(sqlite3.IntegrityError):                  # duplikat (light, relation)
        con.execute("INSERT INTO calibration(light_frame_id, master_frame_id, relation, "
                    "asserted_by) VALUES (1, 2, 'flat', 'horreum')")
    with pytest.raises(sqlite3.IntegrityError):                  # CHECK relation
        con.execute("INSERT INTO calibration(light_frame_id, master_frame_id, relation, "
                    "asserted_by) VALUES (1, 2, 'bogus', 'horreum')")
    with pytest.raises(sqlite3.IntegrityError):                  # NOT NULL master
        con.execute("INSERT INTO calibration(light_frame_id, relation, asserted_by) "
                    "VALUES (1, 'dark', 'horreum')")
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


def _op_0022(con, lid, phase, region=b"ab"):
    con.execute(
        "INSERT INTO inplace_op(location_id, kind, fmt, region_offset, region_length, old_region_z, "
        "new_region_z, write_start, write_end, file_size, file_ino, pre_hash, post_hash, phase, "
        "started_at) VALUES (?, 'commit', 'fits', 0, ?, x'00', x'00', 0, 1, 10, 1, 'a', 'b', ?, 't')",
        (lid, len(region), phase))


def test_0022_jedna_otwarta_operacja_na_lokacje(tmp_path):
    """STRAŻNIK W DDL (0022): na jednej lokacji najwyżej JEDNA operacja otwarta (`writing`/
    `unverified`) - druga oznaczałaby zapis na pliku o nieznanym stanie. Zamknięte mogą się mnożyć.
    Falsyfikator: zdejmij `uq_inplace_op_otwarta` → drugi INSERT przechodzi."""
    con = db.open_db(str(tmp_path / "h.db"))
    _loc_0021(con, 1)
    _op_0022(con, 1, "synced")
    _op_0022(con, 1, "recovered")
    _op_0022(con, 1, "writing")
    with pytest.raises(sqlite3.IntegrityError):
        _op_0022(con, 1, "unverified")
    with pytest.raises(sqlite3.IntegrityError):
        _op_0022(con, 1, "nieznana")
    con.close()


def test_0023_przyrost_na_bazie_v22_wiaze_tylko_operacje_written(tmp_path):
    """Baza v22 z dziennikiem zapisu w miejscu przechodzi 0023: `inplace_op.anchor_sha1` wchodzi
    PUSTA (SQL nie zna bajtów pliku), a wiązanie `pending_changes.inplace_op_id` dostają wyłącznie
    wpisy 'pending'/'failed' TEGO przebiegu i TEJ lokacji, na której operacja commitu czeka w fazie
    `written` - tylko te dokończenie ma czym zamknąć. Wpis 'applied' przy operacji `synced`, wpis
    innego przebiegu i wpis innej lokacji zostają bez wiązania. Druga migracja to no-op.

    Falsyfikator: zdejmij warunek `phase = 'written'` albo `run_id` z backfillu 0023 → wiązanie
    dostaje wpis przy operacji zamkniętej albo wpis cudzego przebiegu."""
    path = str(tmp_path / "v22.db")
    con = db.connect(path)
    for version, filename in db.MIGRATIONS:
        if version <= 22:
            con.executescript(db._migration_sql(filename))
            con.execute(f"PRAGMA user_version = {int(version)}")
    _loc_0021(con, 1)
    _loc_0021(con, 2)
    con.execute("INSERT INTO commits(id, run_id) VALUES (1, 'R'), (2, 'S')")
    for lid, commit_id, phase in ((1, 1, "written"), (2, 2, "synced")):
        con.execute(
            "INSERT INTO inplace_op(location_id, commit_id, kind, fmt, region_offset, region_length, "
            "old_region_z, new_region_z, write_start, write_end, file_size, file_ino, pre_hash, "
            "post_hash, phase, started_at) VALUES (?, ?, 'commit', 'fits', 0, 2, x'00', x'00', 0, 1, "
            "10, 1, 'a', 'b', ?, 't')", (lid, commit_id, phase))
    wpisy = ((1, "R", 1, "failed"), (2, "R", 1, "pending"), (3, "R", 1, "applied"),
             (4, "Q", 1, "failed"), (5, "S", 2, "applied"), (6, "S", 2, "failed"))
    for pid, run, lid, status in wpisy:
        con.execute("INSERT INTO pending_changes(id, run_id, location_id, keyword, op, status) "
                    "VALUES (?, ?, ?, 'OBJECT', 'set', ?)", (pid, run, lid, status))
    con.commit()
    assert db.migrate(con) == db.SCHEMA_VERSION
    assert [r[0] for r in con.execute("SELECT anchor_sha1 FROM inplace_op")] == [None, None]
    wiazanie = {r[0]: r[1] for r in con.execute("SELECT id, inplace_op_id FROM pending_changes")}
    assert wiazanie == {1: 1, 2: 1, 3: None, 4: None, 5: None, 6: None}
    assert db.migrate(con) == db.SCHEMA_VERSION              # idempotencja
    con.close()
