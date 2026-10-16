-- 0044 - ŚLAD WŁASNEGO COFNIĘCIA DROGI ATOMOWEJ (AR-182; kolumny pod AR-127): co cofnięcie commitu
-- drogą atomową (`writeback.write_full_header`) zamierza położyć pod ścieżką, utrwalone PRZED podmianą.
--
-- PRZYROST (jedna nowa tabela + indeks) - zero przebudowy, zero ruszonych wierszy. Tabela wchodzi
-- PUSTA: cofnięcia sprzed migracji śladu nie zostawiły (na kopii żywej bazy 0 backupów drogi atomowej
-- w stanie cofniętym), więc ich ponowienie rozstrzyga dowód całego pliku z koperty backupu.
--
-- DLACZEGO: cofnięcie atomowe nie zostawiało w bazie nic o własnym wyniku. Ponowienie po cofnięciu,
-- które oddało plik inny niż przed commitem (zmiana poza nagłówkiem od commitu, droga semantyczna,
-- backup tekstowy), nie umiało odróżnić własnego wyniku od powrotu pliku spoza Horreum - albo
-- przyjmowało każdy plik z nagłówkiem sprzed commitu („już cofnięte” bez dowodu całego pliku), albo
-- odmawiało także własnemu wynikowi (obietnica „ponowne undo dokończy samą synchronizację” fałszywa).
-- Teraz wynik rozpoznaje się WYŁĄCZNIE parą pełnych odcisków: plik, którego sha1 i nagłówek są parą
-- `result_sha1`/`result_hash` jednego wiersza, JEST wynikiem tego cofnięcia (odcisk treści), a wiersz,
-- po którym podmiana nie zaszła, nigdy się z żadnym plikiem nie zgodzi.
--
-- Wiersz na KAŻDĄ podmianę cofnięcia (backup bywa cofany więcej niż raz - po powrocie pliku spoza
-- Horreum do stanu po commicie). Append-only: nic go nie kasuje; jedyny UPDATE stawia `synced_at`.
--   * `result_sha1`/`result_size` - wersja przygotowana (plik tymczasowy), liczona w akcie składania
--     albo w strumieniu zapisu, bez drugiego odczytu; `result_hash` - jej `header_hash` (formuła skanu);
--   * `byte_exact` - jak `WriteResult.byte_exact` (1 = wynik ma sha1 pliku sprzed commitu, 0 = nie,
--     NULL = koperta bez sha1 pliku sprzed commitu);
--   * `source_sha1`/`source_size` - plik pod ścieżką w chwili przygotowania (pod blokadą): sha1 z tego
--     samego przebiegu składania, a na drodze semantycznej FITS - z pełnego odczytu uchwytu blokady;
--   * `displaced_path` (kopia pliku wypartego; kopia zwrotna wynika z niej - `_nazwa_zwrotna`)
--     i `prepared_path` (plik tymczasowy) - nazwy, które cofnięcie może zostawić na dysku po śmierci
--     procesu w oknie podmiany (AR-127); znane wyłącznie w tej chwili, więc utrwalone teraz, choć
--     rekoncyliacji jeszcze nie ma - jej stan da się dołożyć później bez utraty informacji;
--   * `recorded_at` - utrwalenie wiersza (przed podmianą); `synced_at` - baza wciągnęła ten wynik
--     (transakcja re-syncu cofnięcia albo rozliczenia „już cofnięte”). NULL = podmiana mogła zajść albo
--     nie, a baza wyniku jeszcze nie zna.
CREATE TABLE atomic_undo (
    id             INTEGER PRIMARY KEY,
    backup_id      INTEGER NOT NULL REFERENCES header_backups (id),
    result_sha1    TEXT    NOT NULL CHECK (length(result_sha1) = 40),
    result_size    INTEGER NOT NULL CHECK (result_size >= 0),
    result_hash    TEXT    NOT NULL CHECK (length(result_hash) = 40),
    byte_exact     INTEGER CHECK (byte_exact IN (0, 1)),
    source_sha1    TEXT    NOT NULL CHECK (length(source_sha1) = 40),
    source_size    INTEGER NOT NULL CHECK (source_size >= 0),
    displaced_path TEXT    NOT NULL CHECK (length(displaced_path) > 0),
    prepared_path  TEXT    NOT NULL CHECK (length(prepared_path) > 0),
    recorded_at    TEXT    NOT NULL CHECK (length(recorded_at) > 0),
    synced_at      TEXT    CHECK (synced_at IS NULL OR length(synced_at) > 0)
);
CREATE INDEX idx_atomic_undo_backup ON atomic_undo (backup_id);
