-- 0022 - DZIENNIK ZAPISU W MIEJSCU: `inplace_op` (O5, decyzja usera Q8 2026-09-26).
--
-- PRZYROST (nowa tabela, jak 0003/0005/0011) - zero zmian istniejących tabel, zero wierszy ruszonych.
-- Tabelę pisze WYŁĄCZNIE klinga (`repo.begin_inplace_op` / `repo.set_inplace_op_phase`), wołana przez
-- pisarza `writeback` pod blokadą pliku.
--
-- PO CO. Zapis nagłówka w miejscu (`writeback.write_changes_inplace`) nie jest atomowy: przerwa
-- w połowie zostawia nagłówek ROZDARTY. Jedna tabela niesie DWA cele, bo to ten sam fakt:
--   1. FAZA OPERACJI (astra Z11/Z13): wiersz powstaje PRZED pierwszym bajtem zapisu (`writing`)
--      i niesie wszystko, czego odzysk potrzebuje BEZ parsowania pliku - offset regionu, region
--      stary i planowany wynikowy, zakres zapisu, rozmiar i `st_ino` pliku, hash nagłówka przed
--      i po. Zamyka go weryfikacja (`written`) i re-sync bazy (`synced`). Odzysk (`recover_torn`)
--      dotyczy WYŁĄCZNIE otwartej operacji i dowodzi rozdarcia porównaniem bajtów regionu z jej
--      dwoma stanami - nie zgodnością rozmiaru i próbek, która nie wyklucza cudzej przebudowy.
--   2. IZOLACJA LOKACJI (Q8): lokacja z operacją OTWARTĄ (`writing`, `unverified`) jest wyłączona ze
--      zwykłego skanu (`scan._isolated`): skan rozdartego pliku uznałby go za podmianę treści
--      i rozdwoił klatkę, a marker `unreadable_*` (0006/0019) zrobiłby odwrotność izolacji -
--      wymusza ponowny odczyt. Izolacja trwa do udanego odzysku (`recovered`) albo jawnego
--      zwolnienia ręką (`released`). Stan, nie dziennik: predykat izolacji czyta `phase`, więc
--      nie ma drugiej kolumny na `location`, która mogłaby się z nim rozjechać.
--
-- FAZY: writing (wiersz przed zapisem) → written (weryfikacja zgodna) → synced (re-sync bazy);
-- writing → unverified (zapis przerwany albo weryfikacja rozjechana); writing|unverified →
-- recovered (odzysk przywrócił region stary) | released (człowiek zwolnił izolację).
-- RODZAJ: commit (zapis karty), undo (cofnięcie commitu w miejscu). Odzysk nie zakłada wiersza:
-- pisze tylko bajty z zakresu tej samej operacji i każdy jego stan pośredni jest dalej stanem
-- pośrednim tej operacji, więc przerwany odzysk da się ponowić tą samą drogą.
--
-- REGIONY jako BLOB skompresowany zlib (nagłówki kompresują się kilkukrotnie; ~7,4 tys. operacji
-- wsadu). Strażnik w DDL: jedna OTWARTA operacja na lokację (indeks częściowy) - druga przed
-- zamknięciem pierwszej oznaczałaby zapis na pliku, którego stanu nie znamy.
CREATE TABLE inplace_op (
    id            INTEGER PRIMARY KEY,
    location_id   INTEGER NOT NULL REFERENCES location(id),
    commit_id     INTEGER REFERENCES commits(id),
    kind          TEXT NOT NULL CHECK (kind IN ('commit', 'undo')),
    fmt           TEXT NOT NULL CHECK (fmt IN ('fits', 'xisf')),
    region_offset INTEGER NOT NULL CHECK (region_offset >= 0),
    region_length INTEGER NOT NULL CHECK (region_length > 0),
    old_region_z  BLOB NOT NULL,
    new_region_z  BLOB NOT NULL,
    write_start   INTEGER NOT NULL CHECK (write_start >= 0),
    write_end     INTEGER NOT NULL CHECK (write_end >= write_start AND write_end <= region_length),
    file_size     INTEGER NOT NULL,
    file_ino      INTEGER NOT NULL,
    pre_hash      TEXT NOT NULL,
    post_hash     TEXT NOT NULL,
    phase         TEXT NOT NULL CHECK (phase IN ('writing', 'unverified', 'written', 'synced',
                                                 'recovered', 'released')),
    started_at    TEXT NOT NULL,
    closed_at     TEXT,
    reason        TEXT
);
CREATE INDEX idx_inplace_op_loc ON inplace_op (location_id, phase);
CREATE INDEX idx_inplace_op_commit ON inplace_op (commit_id, location_id);
CREATE UNIQUE INDEX uq_inplace_op_otwarta ON inplace_op (location_id)
    WHERE phase IN ('writing', 'unverified');
