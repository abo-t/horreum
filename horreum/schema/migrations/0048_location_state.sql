-- 0048 - RODOWÓD STANU LOKACJI (AR-421): kto i w jakiej kolejności postawił odcisk pliku (`location.file_sha1`,
-- `location.header_hash`) - zapis kart, cofnięcie, własny powrót pisarza albo treść spoza Horreum.
--
-- PRZYROST (jedna nowa tabela + trzy indeksy) - zero przebudowy, zero ruszonych wierszy. Tabela wchodzi PUSTA,
-- bez zasiewu: wiersz opisuje zatwierdzoną obserwację, a stanu sprzed migracji nikt nie zaobserwował z pochodzeniem
-- (zasiew byłby opisem bieżącego odcisku, nie dowodem, kto go postawił). Lokacja bez wiersza znaczy „historia
-- sprzed 0048 nieznana” - reguła klasy cofnięcia schodzi wtedy do reguły sprzed rodowodu.
--
-- DLACZEGO: klasa cofnięcia backupu widziała łańcuch cofnięć wyłącznie w jednym przebiegu. Po „Cofnij” nowszego
-- zapisu, a potem starszego zapisu tych samych plików z innego przebiegu baza nie miała faktu, że nowszy jest już
-- cofnięty (A → B → A przywracało zapis, który człowiek cofnął). `atomic_undo.id` porządkuje próby, nie domknięcia,
-- a cofnięcie w miejscu nie zostawia śladu w tej sekwencji. Teraz każda transakcja, w której baza poznaje wynik
-- pisarza albo odczyt zmienia odcisk lokacji, dopisuje wiersz - `id` porządkuje ZATWIERDZONE obserwacje stanu
-- jednej lokacji (wiersz wchodzi albo wycofuje się razem z transakcją wołającego; SQLite - jeden pisarz naraz).
-- `id` NIE jest kolejnością zakończenia całych operacji (faza `recovered` odzysku idzie osobną transakcją).
--
-- APPEND-ONLY: nic wiersza nie zmienia ani nie kasuje - historia odcisku to fakt, a reguła klasy idzie po niej
-- wstecz; poprawka stanu to nowy wiersz. Wiersze pisze wyłącznie `repo` (`_dopisz_stan`), ze zdarzeniem.
--   * `origin` - `commit` (zapis kart albo zmiany obiektu, obie drogi), `undo` (cofnięcie obu dróg),
--     `rollback` (własny powrót pisarza do stanu sprzed operacji, która nie doszła - odzysk rozdarcia),
--     `external` (treść spoza pisarza: skan, stosy, uzupełnienie XISF, import, wersja innego pisarza wrócona
--     spod kopii wypartej). Etykieta pisarza wymaga zgodności odczytanego pliku z wynikiem operacji - inaczej
--     `external`;
--   * `commit`/`undo` - wiersz w transakcji, w której baza poznaje wynik pisarza, także bez zmiany odcisku
--     (przypisanie); `rollback`/`external` - wyłącznie przy zmianie `file_sha1` albo `header_hash`;
--   * `backup_id` - czyj zapis (`commit`/`undo`); `inplace_op_id` - operacja zapisu w miejscu (zapis, cofnięcie,
--     odzysk); `atomic_undo_id` - ślad cofnięcia atomowego, którego wynik leży w pliku;
--   * `file_sha1`/`header_hash` - odcisk lokacji PO przejściu (NULL przy pliku nieczytelnym, jak w `location`);
--   * co najwyżej JEDEN wiersz `commit` na backup (indeks unikalny częściowy - bezpiecznik): ponowna obserwacja
--     wyniku tego samego zapisu, także po jego cofnięciu, nie jest nowym zapisem.
CREATE TABLE location_state (
    id             INTEGER PRIMARY KEY,
    location_id    INTEGER NOT NULL REFERENCES location (id),
    origin         TEXT    NOT NULL CHECK (origin IN ('commit', 'undo', 'rollback', 'external')),
    backup_id      INTEGER REFERENCES header_backups (id),
    inplace_op_id  INTEGER REFERENCES inplace_op (id),
    atomic_undo_id INTEGER REFERENCES atomic_undo (id),
    file_sha1      TEXT,
    header_hash    TEXT,
    at             TEXT    NOT NULL CHECK (length(at) > 0),
    CHECK ((origin IN ('commit', 'undo')) = (backup_id IS NOT NULL)),
    CHECK (atomic_undo_id IS NULL OR origin = 'undo'),
    CHECK (origin <> 'rollback' OR inplace_op_id IS NOT NULL)
);
CREATE INDEX idx_location_state_location ON location_state (location_id, id);
CREATE INDEX idx_location_state_backup ON location_state (backup_id, id) WHERE backup_id IS NOT NULL;
CREATE UNIQUE INDEX idx_location_state_commit ON location_state (backup_id) WHERE origin = 'commit';
