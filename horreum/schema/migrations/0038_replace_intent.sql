-- 0038 - ZAMIAR PODMIANY (AR-64): co pisarz drogi atomowej zamierza zrobić z plikiem, utrwalone RAZEM
-- z backupem, PRZED pierwszą podmianą.
--
-- PRZYROST (jedna nowa tabela) - zero przebudowy, zero ruszonych wierszy. Tabela wchodzi PUSTA:
-- backupy sprzed migracji nie mają zamiaru i rekoncyliują się dawną regułą (nagłówek na dysku).
--
-- DLACZEGO: podmiana systemowa (`ReplaceFileW`) odkłada plik wyparty pod nazwę kopii, a dopiero
-- rewalidacja tej kopii mówi, czy w oknie podmiany ktoś inny zmienił plik. Proces, który zginął
-- między podmianą a rewalidacją, zostawiał kopię pod losową nazwą, której baza nie znała, a
-- rekoncyliacja (po samym nagłówku) potwierdzała commit i osierocała cudzą wersję - cofnięcie
-- przywróciłoby potem wersję sprzed niej. Teraz rekoncyliacja zna wszystkie pliki próby i rozpoznaje
-- każdą wersję WYŁĄCZNIE pełnym sha1:
--   * A = plik sprzed zapisu - `RegionBackup.file_sha1` i rozmiar z koperty backupu;
--   * N = przygotowana wersja (plik tymczasowy) - `prepared_sha1`/`prepared_size`, liczone
--     w strumieniu zapisu pliku tymczasowego, bez drugiego odczytu;
--   * B = wersja innego pisarza zastana pod nazwą kopii - `displaced_sha1`/`displaced_size`,
--     utrwalone przed powrotem jej pod ścieżkę.
-- Nazwy plików: `displaced_path` (kopia pliku wypartego, K), `return_path` (kopia zwrotna - tu trafia
-- nasza wersja, gdy wersja innego pisarza wraca pod ścieżkę, Z; wyliczana z K, znana od początku),
-- `prepared_path` (plik tymczasowy, T).
--
-- `phase`: `prepared` (zamiar utrwalony, podmiana mogła zajść albo nie) → `returning` (rekoncyliacja
-- zapisała B i wraca jego wersję pod ścieżkę) → `returned` (powrót wykonany i sprawdzony, sprzątanie
-- kopii zwrotnej w toku) → `closed` z `outcome`: `replaced` (pod ścieżką N - commit zaszedł),
-- `not_replaced` (pod ścieżką A - podmiany nie było albo kopia wróciła na miejsce), `returned`
-- (pod ścieżką wersja innego pisarza z okna podmiany, nasza przepadła), `kept` (stan, którego nie da
-- się dowieść - wszystkie pliki zostają, a ich ścieżki niesie zdarzenie `location.displaced_kept`).
-- `kept_paths` = pliki zostawione OBOK ścieżki (kopia wyparta, zwrotna, tymczasowy) przy `kept` -
-- ze stanu liczy je wiersz Porządków „Kopie zostawione do oka”, póki leżą na dysku.
-- Każda faza zapisuje się PRZED mutacją pliku, której dotyczy: śmierć w dowolnym miejscu zostawia
-- stan, z którego ponowienie wie, co już zaszło. Żaden krok nie kasuje pliku, którego bajtów nie
-- rozpoznał pełnym sha1 jako A albo N.
CREATE TABLE replace_intent (
    backup_id      INTEGER PRIMARY KEY REFERENCES header_backups (id),
    displaced_path TEXT    NOT NULL CHECK (length(displaced_path) > 0),
    return_path    TEXT    NOT NULL CHECK (length(return_path) > 0),
    prepared_path  TEXT    NOT NULL CHECK (length(prepared_path) > 0),
    prepared_sha1  TEXT    NOT NULL CHECK (length(prepared_sha1) = 40),
    prepared_size  INTEGER NOT NULL CHECK (prepared_size >= 0),
    displaced_sha1 TEXT    CHECK (displaced_sha1 IS NULL OR length(displaced_sha1) = 40),
    displaced_size INTEGER,
    phase          TEXT    NOT NULL DEFAULT 'prepared'
                   CHECK (phase IN ('prepared', 'returning', 'returned', 'closed')),
    outcome        TEXT    CHECK (outcome IN ('replaced', 'not_replaced', 'returned', 'kept')),
    kept_paths     TEXT    NOT NULL DEFAULT '[]'
                   CHECK (json_valid(kept_paths) AND json_type(kept_paths) = 'array'),
    opened_at      TEXT    NOT NULL CHECK (length(opened_at) > 0),
    closed_at      TEXT,
    CHECK ((phase = 'closed') = (outcome IS NOT NULL)),
    CHECK ((phase = 'closed') = (closed_at IS NOT NULL)),
    CHECK ((displaced_sha1 IS NULL) = (displaced_size IS NULL)),
    CHECK (phase NOT IN ('returning', 'returned') OR displaced_sha1 IS NOT NULL)
);
