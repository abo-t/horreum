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
# 0007 to jedyna dotąd PRZEBUDOWA tabeli (P6/D-X-14): header_backups.hdu_index traci NOT NULL,
# bo XISF nie zna pojęcia HDU (D-X-7) i pisarz XISF wybuchałby PO mutacji pliku, bez backupu.
# Dane kopiowane 1:1 (tabela append-only = historia undo).
# 0008 to PRZYROST (oś KALIBRACJI, #6): calibration_profile + calibration_fact +
# frame.calibration_profile_id. `header.set_temp` wchodzi jako kolumna GENERATED z `raw_json`
# (D-C-2) — nastawa jest ODCZYTYWANA z zeznania, nie kopiowana, więc migracja NIE ma backfillu
# i wartość nie może się zestarzeć po writebacku.
# 0009 to PRZEBUDOWA tabeli `calibration` (RODOWÓD light↔master, C4/#6): pusty szkielet z 0002
# dostaje NOT NULL + CHECK(relation) + UNIQUE(light_frame_id, relation). UNIQUE (nie kod) trzyma
# idempotencję rodowodu; tabela dowodnie pusta, więc INSERT SELECT kopiuje 0 wierszy.
# 0010 to PRZYROST (DSLR/RAW, #2): frame.kind_source — prowieniencja rodzaju (header|path|NULL).
# ADD COLUMN, wiersze sprzed migracji dostają NULL; re-skan/nowy ingest ustawia jawnie.
# 0011 to PRZYROST (planer T4): target_plan (kuratela celów, klucz = kanon KATALOGU, nie FK do
# `object`) + telescope.in_park (trójstan 1|0|NULL). Oba niosą fakt o PRZYSZŁOŚCI — czego archiwum
# nie zna z definicji, więc backfillu nie ma i mieć nie może (D-0731-4, D-T3-d).
# 0012 to PRZEBUDOWA obu tabel rodowodu stosów (I-2c, P-I): `integration` dostaje tożsamość na
# KLATCE MASTERA (UNIQUE) zamiast na wywnioskowanym zbiorze wejść, `integration_input` — UNIQUE
# i trójstan `asserted_by` (history|window|user). Obie były pustym szkieletem z 0002 (zero wierszy,
# zero pisarzy), więc INSERT SELECT kopiuje 0 wierszy.
# 0013 to PRZEBUDOWA `saved_query` (I-1, P-I): `sql_text` → `spec_json` + `updated_at`. Perspektywa
# Horreum nigdy nie była SQL-em (grid składa JSON-spec), a od D-P-I-3 mieszka w BAZIE zamiast
# w rejestrze użytkownika — nazwany widok jest własnością ARCHIWUM, nie komputera.
# 0014 to PRZYROST (#DR2 segment R4): frame.superseded_by — treść pod ścieżką klatki podmieniona,
# nowa tożsamość niesie plik dalej. Kolumna wchodzi PUSTA; wypełnia ją pass `horreum supersede`
# (guardy: żywotność, ostatni event per klatka, odmowa cyklu), nie migracja — kanon jak 0004/0011.
# 0015 to PRZYROST (#DR2 segment R1): frame.config_source — oś sprzętu wskazana RĘKĄ (`user`)
# vs wyliczona z nagłówka (NULL). Kolumna wchodzi PUSTA i taka zostaje dla archiwum: wypełnia ją
# gest z kolejki przeglądu, bo RAW przez teleskop nie ma czym zeznać (E3-3), a plik jest read-only.
# 0016 to PRZEBUDOWA `integration` (#DR2 segment R2): kolumna `utc_offset_min` (trójstan NULL|0|minuty)
# plus token `offset_unknown` w CHECK-u powodów. Sama kolumna poszłaby ADD COLUMN — CHECK wymusza
# przebudowę. PIERWSZA przebudowa tabeli z REALNYMI danymi (128 wierszy + 3367 w dziecku), więc
# INSERT SELECT kopiuje KOMPLET kolumn po obu stronach, a nie podzbiór jak 0012.
# 0017 to PRZYROST (R-S2b-3): frame.object_cleared_id — PAMIĘĆ nagrobka, czyli obiekt, który ręka
# zdjęła. Do S2b nagrobek zapisywał sam FAKT odmowy bez jej PRZEDMIOTU, więc masowe cofnięcie nie
# miało drogi powrotu. STAN, nie dziennik: klatka cofnięta dwukrotnie ma dwa `object.cleared`,
# a `transfer_human_facts` emituje ten verb bez `was_object_id`. CHECK wiąże pamięć z nagrobkiem.
# 0018 to PRZYROST (D-OW-3/R2): frame.retired_at — WERDYKT RĘKI „pliku tej klatki już nie szukam".
# Klatka wypada z kubełków roboczych, ZOSTAJE w archiwum i w godzinach (nie ma następczyni, która
# by je przejęła — inaczej niż przy `superseded_by`). Kolumna wchodzi PUSTA; strażnika w DDL nie
# ma i mieć nie może (warunek jest zdaniem o `location`), więc pilnuje go klinga, a deklaratywnie
# `audit.retire_invariants` + kryterium §5.17 — wzorem `supersede_invariants`/§5.15.
# 0019 to PRZYROST (P4-2): location.unreadable_kind ('io'|'parse'|'db') + location.unreadable_reason -
# marker 0006 niósł sam CZAS, więc powierzchnia oskarżała plik także wtedy, gdy zawiódł dysk. STAN,
# nie dziennik: powód szukany w `event` po ścieżce gubił się przy przemianowanej kopii. 'db' = błąd
# bazy po naszej stronie (zapis albo brama), nie fakt o pliku - marker stoi, bo wymusza re-odczyt.
# CHECK wiąże oba fakty z markerem (powód bez markera = sprzeczność); marker bez rodzaju zostaje
# legalny: rodzaj nieznany - wiersz sprzed 0019 albo wyjątek bez kodu systemu, nierozstrzygnięty.
# 0020 to PRZYROST (G2-1d): integration.raw_unreferenced - UWAGA obok jednowartościowego werdyktu
# rodowodu: ile RAW-ów przebieg nie umiał umieścić w czasie przy stosie, którego werdykt mówi co
# innego (pula mieszana RAW+FITS). Kolumna wchodzi PUSTA, pisze ją przebieg przez klingę. CHECK:
# `> 0` (brak uwagi ma jedną postać - NULL) i nie przy `offset_unknown` (werdykt mówi to samo).
# 0021 to PRZYROST: fakty KOPII z jej nagłówka na `location` - liczba i role obrazów (XISF) oraz
# zeznanie pól, które karmią osie klatki (`hdr_*`), z kotwicą `hdr_hash` (CHECK: NULL albo równa
# `header_hash`, więc zmiana odcisku bez odświeżenia faktów jest błędem, nie cichą nieprawdą).
# Kolumny wchodzą PUSTE; wiersze sprzed migracji uzupełnia etap Dostawy `scan.backfill_copy_facts`.
# 0022 to PRZYROST (nowa tabela, O5/Q8): dziennik zapisu nagłówka w miejscu `inplace_op` - faza
# operacji z regionem starym i wynikowym (odzysk rozdartego nagłówka bez parsowania pliku) i zarazem
# izolacja lokacji z operacją otwartą od zwykłego skanu. Tabela wchodzi PUSTA.
# 0023 to PRZYROST (dwie kolumny ADD COLUMN): `inplace_op.anchor_sha1` - kotwica kontroli danych
# utrwalona przy operacji (dawniej mutowalna `location.file_sha1`) - i `pending_changes.inplace_op_id`
# - wiersze stagingu zapisane przez operację, które dokończenie oznacza atomowo z fazą. Backfill
# wyłącznie wiązania dla operacji commitu w fazie `written` (kotwicy SQL nie zna).
# 0024 to PRZYROST (ADD COLUMN, AR-37): `header_backups.unreplaced_at` - backup drogi atomowej,
# po którym pisarz pliku NIE podmienił (wyłącznie odmowa straży podmiany - wynik 'blocked'; awaria
# samego `os.replace` mogła podmienić plik na udziale, więc znacznika nie dostaje). Cofnięcie
# commitu go pomija. Kolumna wchodzi PUSTA (NULL = jak dotąd); backfillu nie ma - SQL nie wie,
# który backup poprzedził podmianę.
# 0025 to PRZYROST (ADD COLUMN, AR-33): `location.hdr_rule` - numer reguły koercji, którą zebrano
# fakty kopii `hdr_*`. Zmiana koercji podnosi stałą `resolve.headers.COPY_TESTIMONY_RULE`, a sterownik
# uzupełnienia dociąga kopie starszej reguły, zamiast porównywać je z nowymi. Backfill: 1 przy
# zebranych faktach (jedyna reguła od 0021 - stempel jest odczytem, nie domysłem), NULL przy reszcie.
# 0026 to PRZYROST (CREATE TABLE + ADD COLUMN, AR-10): `stack_version_kept` - werdykt człowieka
# „zostawiam wszystkie" grupy wersji stosów (wiersz na członka, wspólny klucz gestu) - oraz
# `integration.creation_time` (`XISF:CreationTime`, data stosów sprzed sygnatury integracji). Tabela
# wchodzi pusta, kolumnę wypełnia najbliższy przebieg rodowodu stosów - SQL tego faktu nie zna.
MIGRATIONS = [
    (2, "0002_initial.sql"),
    (3, "0003_writeback.sql"),
    (4, "0004_observatory.sql"),
    (5, "0005_rename.sql"),
    (6, "0006_unreadable.sql"),
    (7, "0007_backup_hdu_nullable.sql"),
    (8, "0008_calibration.sql"),
    (9, "0009_calibration_lineage.sql"),
    (10, "0010_kind_source.sql"),
    (11, "0011_target_plan.sql"),
    (12, "0012_stack_lineage.sql"),
    (13, "0013_saved_query_spec.sql"),
    (14, "0014_superseded.sql"),
    (15, "0015_config_source.sql"),
    (16, "0016_integration_offset.sql"),
    (17, "0017_object_cleared_memory.sql"),
    (18, "0018_frame_retired.sql"),
    (19, "0019_location_unreadable_reason.sql"),
    (20, "0020_integration_raw_unreferenced.sql"),
    (21, "0021_location_copy_facts.sql"),
    (22, "0022_inplace_op.sql"),
    (23, "0023_inplace_anchor_link.sql"),
    (24, "0024_backup_unreplaced.sql"),
    (25, "0025_location_hdr_rule.sql"),
    (26, "0026_stack_version_kept.sql"),
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
    # TRWAŁOŚĆ BACKUPU (astra, warunek 5): backup nagłówka i faza zapisu w miejscu MUSZĄ przetrwać
    # utratę zasilania zaraz po commicie transakcji - dopiero wtedy wolno ruszyć plik. W WAL tylko
    # FULL synchronizuje commit na dysk (NORMAL może zgubić ostatnie transakcje). Domyślna wartość
    # bundlowanego SQLite to dziś FULL, ale domyślna to cudza decyzja kompilacji - ustawiamy jawnie.
    con.execute("PRAGMA synchronous = FULL")
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
            _apply_migration(con, version, _migration_sql(filename))
            current = version
    return current


def _apply_migration(con, version, sql):
    """Jedna migracja RAZEM z podniesieniem `user_version` - w JEDNEJ transakcji.

    DLACZEGO: goły `executescript` zatwierdza każdą instrukcję osobno, a `user_version` szło
    dopiero po nim. Awaria w środku skryptu (brak miejsca, zerwany dysk, zabity proces) zostawiała
    bazę z częścią `ALTER TABLE` i STARĄ wersją - następne otwarcie powtarzało migrację od początku
    i wybuchało na `duplicate column name`, czyli baza nie otwierała się wcale. W transakcji albo
    przechodzi całość razem z numerem wersji, albo nic.

    `BEGIN` stoi WEWNĄTRZ skryptu, bo `executescript` przed startem zatwierdza otwartą transakcję
    (zewnętrzny `BEGIN` zostałby zamknięty, zanim ruszy pierwsza instrukcja migracji). `IMMEDIATE`
    bierze blokadę zapisu od razu - równoległy pisarz czeka na `busy_timeout`, zamiast wpaść w środek.
    Migracje, które same ustawiają `PRAGMA user_version` w treści (0008, 0009, 0012, 0013, 0016),
    działają tak samo: numer wersji jest częścią nagłówka bazy i wraca razem z `ROLLBACK`, a końcowe
    ustawienie niżej jest tym samym numerem. Żadna migracja nie niesie instrukcji wrogich transakcji
    (`VACUUM`, `PRAGMA foreign_keys`, `PRAGMA journal_mode`) - taka musiałaby dostać własną drogę.

    Średnik na osobnym wierszu domyka ostatnią instrukcję skryptu, gdyby plik kończył się bez niego
    (pusta instrukcja jest dla SQLite no-opem). PRAGMA nie przyjmuje bindowania - f-string z literału
    int (version z MIGRATIONS). Wyjątek: `ROLLBACK`, gdy transakcja jeszcze stoi, i rzut dalej
    (EXPECT - wołający dostaje błąd migracji, baza zostaje w wersji sprzed niej)."""
    script = f"BEGIN IMMEDIATE;\n{sql}\n;\nPRAGMA user_version = {int(version)};\nCOMMIT;\n"
    try:
        con.executescript(script)
    except BaseException:
        if con.in_transaction:
            con.rollback()
        raise


def open_db(path):
    """Otwórz + zmigruj. Główne wejście dla CLI/skanu."""
    con = connect(path)
    migrate(con)
    return con
