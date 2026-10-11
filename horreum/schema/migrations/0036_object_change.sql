-- 0036 - ZMIANA OBIEKTU RAZEM Z PLIKIEM (AR-17 krok 3, D-1011-5): przebieg gestu „Zmień obiekt…”
-- i „Uzgodnij”, stan klatki sprzed zmiany obiektu i katalogi, które gest założył albo usunął.
--
-- PRZYROST (trzy nowe tabele) - zero przebudowy, zero ruszonych wierszy. Tabele wchodzą PUSTE:
-- wypełnia je staging gestu (`repo.stage_object_change`) i sterownik (`writeback.commit_object_change`,
-- `writeback.undo_object_change`). Zapis WYŁĄCZNIE przez klingę `repo`; wiersze są księgowością
-- przebiegu (jak `pending_changes`/`pending_renames`) - bez eventów. Faktem domenowym jest zmiana
-- obiektu klatki (para `object.unassigned`/`object.assigned`) i relokacja (`location.renamed`).
--
-- DLACZEGO W BAZIE, NIE W PAMIĘCI OKNA (D-1011-5): gest to trzy media (baza, nazwa i katalog
-- pliku, karta w nagłówku). Cofnięcie, które zna stan sprzed tylko z pamięci okna, nie przeżywa
-- awarii procesu, a ponowienie po awarii nie wie, co już zrobiono. Sterownik i cofnięcie odtwarzają
-- WSZYSTKO z `run_id`: cel (`object_change_run`), pozycje (`pending_object_change`), przeniesienia
-- (`pending_renames`), karty (`pending_changes` + `commits`) i katalogi (`run_dir`).

-- PRZEBIEG GESTU: cel zapisany przy stagingu. `mode`: `change` = „Zmień obiekt…” (baza dostaje
-- obiekt ręką, pola celu wypełnione - forma karty obowiązkowa, bo gest bez niej odmawia celu
-- przed planem), `align` = „Uzgodnij” (obiekt zostaje, plik dogania obiekt klatki - pola celu puste).
-- Obiekt i alias zakłada sterownik przy pierwszej pozycji, która naprawdę dostaje obiekt (nie
-- staging): porzucony podgląd nie zostawia pustego obiektu. `status`: `staged` → `applied`
-- (przebieg sterownika doszedł do końca listy) → `undoing` (cofnięcie zlecone - zapis przebiegu już
-- się nie wznowi, ponowienie cofnięcia wznawia pozycje) → `undone` (cofnięcie domknęło wszystkie
-- pozycje i katalogi).
CREATE TABLE object_change_run (
    run_id     TEXT PRIMARY KEY CHECK (length(run_id) > 0),
    mode       TEXT NOT NULL CHECK (mode IN ('change', 'align')),
    canon      TEXT,
    catalog    TEXT,
    kind       TEXT,
    alias_norm TEXT CHECK (alias_norm IS NULL OR length(alias_norm) > 0),
    card_form  TEXT,
    created_at TEXT NOT NULL CHECK (length(created_at) > 0),
    status     TEXT NOT NULL DEFAULT 'staged'
               CHECK (status IN ('staged', 'applied', 'undoing', 'undone')),
    CHECK ((mode = 'change' AND canon IS NOT NULL AND kind IS NOT NULL AND card_form IS NOT NULL)
        OR (mode = 'align' AND canon IS NULL AND catalog IS NULL AND kind IS NULL
            AND alias_norm IS NULL AND card_form IS NULL))
);

-- POZYCJA PRZEBIEGU = jedna klatka z jedną obecną kopią. Kolumny:
--   * `old_path` + `expected_mtime` - ścieżka kopii i jej `mtime` z PODGLĄDU, dla KAŻDEJ pozycji
--     (także bez przeniesienia): sterownik pisze wyłącznie plik, który podgląd pokazał - kopia pod
--     inną ścieżką albo z innym `mtime` w bazie lub na dysku = odmowa bez zapisu;
--   * `object_change` - czy gest zmienia obiekt tej klatki w bazie (0 przy „Uzgodnij” i przy celu
--     równym bieżącemu obiektowi);
--   * `expected_*` - trójca `(object_id, object_source, object_cleared_id)` z chwili podglądu: CAS
--     ręki (stan inny w chwili zapisu = pozycja pominięta, zero zapisu);
--   * `object_id` + `before_*` - obiekt, który gest ZAPISAŁ, i stan sprzed, utrwalone W TEJ SAMEJ
--     transakcji co zmiana obiektu klatki. `object_id IS NULL` = baza tej pozycji nie została
--     zmieniona (jeszcze, wcale albo zmiana cofnięta w tym samym przebiegu) - cofnięcie bazy jej nie
--     dotyczy. `before_*` może być w całości NULL (klatka bez obiektu) - dlatego flagą jest `object_id`;
--   * `rename_id` - wiersz przeniesienia (`pending_renames`) albo NULL (plik już na miejscu);
--   * `mkdirs` - katalogi celu do założenia z PODGLĄDU (tablica JSON, od najpłytszego): sterownik
--     zakłada wyłącznie te, których w chwili ruchu nadal nie ma - poziom spoza listy nie powstaje
--     (podgląd pokazał, ile katalogów gest założy, i zapis nie ma prawa założyć więcej);
--   * `status` - wynik pozycji: `pending` (nietknięta), `applied`, `skipped` (dryf, kopia zniknęła -
--     nic nie zrobiono), `blocked` (odmowa, zrobione kroki pozycji cofnięte), `failed` (stan częściowy,
--     droga naprawy w `reason`), `undone` (cofnięcie domknęło pozycję);
--   * `undo_phase` - ostatnia domknięta faza cofnięcia pozycji: `card` (karta wróciła albo nie było
--     czego cofać) → `file` (plik wrócił) → `db` (baza przywrócona albo nie było czego). Ponowienie
--     cofnięcia wznawia pierwszą niedomkniętą fazę; `db` idzie razem ze statusem `undone`.
CREATE TABLE pending_object_change (
    id                  INTEGER PRIMARY KEY,
    run_id              TEXT    NOT NULL REFERENCES object_change_run (run_id),
    frame_id            INTEGER NOT NULL REFERENCES frame (id),
    location_id         INTEGER NOT NULL REFERENCES location (id),
    old_path            TEXT    NOT NULL CHECK (length(old_path) > 0),
    expected_mtime      TEXT,
    object_change       INTEGER NOT NULL CHECK (object_change IN (0, 1)),
    expected_object_id  INTEGER REFERENCES object (id),
    expected_source     TEXT,
    expected_cleared_id INTEGER REFERENCES object (id),
    object_id           INTEGER REFERENCES object (id),
    before_object_id    INTEGER REFERENCES object (id),
    before_source       TEXT,
    before_cleared_id   INTEGER REFERENCES object (id),
    rename_id           INTEGER REFERENCES pending_renames (id),
    mkdirs              TEXT    NOT NULL DEFAULT '[]'
                        CHECK (json_valid(mkdirs) AND json_type(mkdirs) = 'array'),
    status              TEXT    NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'applied', 'skipped', 'blocked', 'failed',
                                          'undone')),
    reason              TEXT,
    undo_phase          TEXT CHECK (undo_phase IN ('card', 'file', 'db')),
    CHECK (object_id IS NULL OR object_change = 1),
    CHECK (object_id IS NOT NULL
           OR (before_object_id IS NULL AND before_source IS NULL AND before_cleared_id IS NULL)),
    CHECK ((status = 'undone') = (undo_phase IS 'db')),
    CHECK (mkdirs = '[]' OR rename_id IS NOT NULL),
    UNIQUE (run_id, frame_id)
);
CREATE INDEX idx_poc_run ON pending_object_change (run_id, status);
CREATE INDEX idx_poc_frame ON pending_object_change (frame_id);

-- KATALOGI GESTU: wiersz = ZAMIAR zatwierdzony własną transakcją PRZED `os.mkdir`/`os.rmdir`
-- (`opened_at`), `done_at` po mutacji. `action`: `created` (gest założył katalog celu), `removed`
-- (gest usunął katalog źródłowy, który opróżnił), `restored` (cofnięcie założyło stary katalog,
-- którego nie było - wraca do niego plik). WŁASNOŚĆ: usuwamy WYŁĄCZNIE katalog `created` z `done_at`
-- (założony przez gest na pewno) i pusty; `undone_at` = chwila tego usunięcia. Zamiar bez `done_at`,
-- przy którym katalog istnieje, to własność niepewna (zginęliśmy między mutacją a zapisem albo
-- katalog założył ktoś inny) - nigdy nie usuwany automatycznie, zostaje do oka. Ścieżka bez
-- wielkości liter (`COLLATE NOCASE`): udział `R:` ich nie rozróżnia, więc `IC405` i `ic405` to ten
-- sam katalog i ten sam wiersz.
CREATE TABLE run_dir (
    id        INTEGER PRIMARY KEY,
    run_id    TEXT NOT NULL REFERENCES object_change_run (run_id),
    path      TEXT NOT NULL COLLATE NOCASE CHECK (length(path) > 0),
    action    TEXT NOT NULL CHECK (action IN ('created', 'removed', 'restored')),
    opened_at TEXT NOT NULL CHECK (length(opened_at) > 0),
    done_at   TEXT,
    undone_at TEXT,
    CHECK (undone_at IS NULL OR (action = 'created' AND done_at IS NOT NULL)),
    UNIQUE (run_id, path, action)
);
