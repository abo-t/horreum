-- 0034 - HISTORIA STOSU W BAZIE, ALIASY NAZW LIGHTÓW, PODSTAWA RODOWODU (AR-87, AR-108, E4-9).
--
-- PRZYROST (trzy nowe tabele + ADD COLUMN na `integration`) - zero przebudowy, zero ruszonych wierszy.
-- Tabele wchodzą PUSTE: historię wypełnia pisarz skanu (`rec.history`) i osobny sterownik
-- uzupełnienia (jeden odczyt nagłówka stosu bez wiersza), aliasy - import zapisu przenosin Custos
-- i klinga zmiany nazwy; kolumny `integration` - najbliższy przebieg rodowodu stosów. SQL tych
-- faktów nie zna: siedzą w plikach na udziale i w zewnętrznym dzienniku przenosin.
--
-- HISTORIA STOSU (`stack_history` + `stack_history_input`). Rodowód stosów czytał tabelę `images`
-- z `PixInsight:ProcessingHistory` z PLIKU przy każdym przebiegu (193 stosy, 86,7 MB XML z `R:`
-- na Dostawę). Zeznanie należy do KOPII (dwie kopie jednej klatki mogą nieść różne nagłówki, 0021),
-- więc wiersz wisi na `location`, a kotwicą jest `hdr_hash` - odcisk nagłówka, z którego historię
-- przeczytano. Czytelnik bierze wiersz wyłącznie przy równości z bieżącym `location.header_hash`;
-- rozjazd (zapis w miejscu zmienił nagłówek) znaczy „zwietrzałe” i wraca do pliku. `declared_rows`
-- = atrybut `rows` tabeli `images` (NULL = historii integracji brak; wiersz i tak stoi, bo „przeczytano
-- i nie ma” to inny fakt niż „nie czytano”). Wejścia osobno, w kolejności dokumentu (`seq` od 0):
-- ścieżka jak w pliku (nazwa z czasu obróbki), `enabled`, `has_drizzle`, temperatura z nazwy WBPP.
--
-- ALIASY NAZW (`light_name_alias`). Historia stosu zapisuje nazwy lightów z chwili obróbki, a Custos
-- przemianował 23 637 plików (zmierzone 2026-10-11) - bieżąca nazwa lokacji milczy w 33/33 stosach
-- z historią. Alias = rdzeń dawnej nazwy (`resolve.stack.raw_stem`) przypięty do klatki. Źródła:
-- `custos` (jednorazowy import łańcucha `moves`) i `horreum` (stara nazwa przy zmianie nazwy przez
-- Horreum). UNIQUE(stem, frame_id) = idempotencja dopisu; ten sam rdzeń przy DWÓCH klatkach jest
-- dozwolony w tabeli i znaczy „nazwa niejednoznaczna” - czytelnik odmawia, nie wybiera.
--
-- PODSTAWA RODOWODU na `integration`:
--   * `lineage_basis` - na czym stoi ranga `history`: `name` (pełny, unikalny zbiór po nazwach
--     z historii), `temp` (podzbiór okna po temperaturach), `count` (okno równe liczbie wierszy
--     historii); NULL, gdy wejść `history` nie ma;
--   * `outside_window` - 1, gdy zbiór po nazwach sięga klatek spoza okna nagłówka stosu;
--   * `used_rows` - N werdyktu „plik użył N z M klatek okna” (M = liczba wierszy `window`).
--   CHECK wiąże `outside_window` z podstawą `name` (tylko nazwy wychodzą poza okno).
CREATE TABLE stack_history (
    location_id   INTEGER PRIMARY KEY REFERENCES location (id),
    hdr_hash      TEXT    NOT NULL CHECK (length(hdr_hash) > 0),
    declared_rows INTEGER CHECK (declared_rows IS NULL OR declared_rows >= 0),
    tool          TEXT    CHECK (tool IS NULL OR length(tool) > 0),
    creation_time TEXT    CHECK (creation_time IS NULL OR length(creation_time) > 0)
);

CREATE TABLE stack_history_input (
    location_id INTEGER NOT NULL REFERENCES stack_history (location_id),
    seq         INTEGER NOT NULL CHECK (seq >= 0),
    path        TEXT    NOT NULL,
    enabled     INTEGER NOT NULL CHECK (enabled IN (0, 1)),
    has_drizzle INTEGER NOT NULL CHECK (has_drizzle IN (0, 1)),
    temp_c      REAL    CHECK (temp_c IS NULL OR typeof(temp_c) = 'real'),
    PRIMARY KEY (location_id, seq)
);

CREATE TABLE light_name_alias (
    frame_id INTEGER NOT NULL REFERENCES frame (id),
    stem     TEXT    NOT NULL CHECK (length(stem) > 0),
    source   TEXT    NOT NULL CHECK (source IN ('custos', 'horreum')),
    UNIQUE (stem, frame_id)
);

CREATE INDEX idx_light_name_alias_frame ON light_name_alias (frame_id);

ALTER TABLE integration ADD COLUMN lineage_basis TEXT
    CHECK (lineage_basis IS NULL OR lineage_basis IN ('name', 'temp', 'count'));
ALTER TABLE integration ADD COLUMN outside_window INTEGER NOT NULL DEFAULT 0
    CHECK (outside_window IN (0, 1))
    CHECK (outside_window = 0 OR lineage_basis = 'name');
ALTER TABLE integration ADD COLUMN used_rows INTEGER
    CHECK (used_rows IS NULL OR used_rows >= 0);
