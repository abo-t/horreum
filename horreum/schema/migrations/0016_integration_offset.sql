-- 0016 — ODNIESIENIE CZASU stosu: integration.utc_offset_min (#DR2 segment R2, D-DR-1).
--
-- PRZEBUDOWA `integration` — i to jest WYMUSZENIE, nie wybór. Sama kolumna poszłaby zwykłym
-- ADD COLUMN (jak 0014/0015), ale ta migracja dokłada TAKŻE token `offset_unknown` do CHECK-a
-- na `unresolved_reason` (0012:76-78), a SQLite nie umie zmienić CHECK-a inaczej niż przez
-- CREATE new + INSERT SELECT + DROP + RENAME. Wzorzec i taniec wokół FK — jak 0012.
--
-- RÓŻNICA WOBEC 0012, KTÓRA RZĄDZI TU WSZYSTKIM: tamta migracja przebudowywała tabele DOWODNIE
-- PUSTE (zero wierszy, zero pisarzy), więc INSERT SELECT kopiował nic. Tu tabele są PEŁNE —
-- na żywym archiwum 128 wierszy `integration` i 3367 `integration_input`. Kopiujemy zatem
-- KOMPLET kolumn co do jednej, a nie wybrany podzbiór jak `0012:81-82`; pominięta kolumna
-- oznaczałaby cichą utratę rodowodu 128 gotowych obrazów.
--
-- CO ZNACZY `utc_offset_min` — TRÓJSTAN NAZWANY (D-DR-1):
--   * `NULL`  = odniesienie NIEZNANE. Nie to samo co UTC — stos z materiałem RAW i tym stanem
--               melduje `offset_unknown`, czyli mówi „nie wiem", zamiast udawać `no_candidates`;
--   * `0`     = czas w UTC. Fakt, nie brak — ktoś to rozstrzygnął i tak ma zostać zapisane;
--   * wartość = minuty przesunięcia.
-- ZNAK: `lokalny = UTC + offset`. IC443 `+60`, LMC `+120` (zmierzone: mm:ss zgodne przy różnicy
-- pełnych godzin). Kandydat wraca więc do odniesienia mastera przez ODJĘCIE offsetu.
--
-- DLACZEGO NA INTEGRACJI, A NIE NA KLATCE (D-DR-1, wariant przyjęty po pomiarze): świadkiem
-- offsetu jest OKNO MASTERA — porównanie `window_start` z `date_obs` materiału trafia 7/7. Klatka
-- takiego świadka nie ma, a `frame.utc_offset_min` kazałby pytać o offset w 34 folderach, które
-- nie mają żadnego konsumenta. Fakt mieszka tam, gdzie da się go DOWIEŚĆ.
--
-- POLE JEST POZA LISTĄ `repo.upsert_integration` (`repo.py`, literalny SQL) — ŚWIADOMIE i to
-- jest zaleta do UTRZYMANIA, nie przypadek: przebieg rodowodu przepisuje głowę integracji przy
-- każdej zmianie faktów, a offset jest WERDYKTEM CZŁOWIEKA. Gdyby wszedł do tamtej listy, pierwszy
-- „Przetwórz wszystko" po geście zdejmowałby go z powrotem do NULL — dokładnie ta patologia,
-- przed którą R1b broni ręcznego configu.
--
-- NOWY TOKEN `offset_unknown` — powód, którego przed R2 nie było czym wypowiedzieć. Stos, którego
-- materiał leży w RAW-ach, a odniesienia nikt nie wskazał, dotąd meldował `no_candidates`, czyli
-- NIEPRAWDĘ: kandydaci są, tylko okno liczy w innym zegarze. Cicha nieprawda jest gorsza niż brak
-- odpowiedzi (kanon 0012 pkt 3), a powierzchnia dostaje z tego receptę zamiast ślepego zaułka.
--
-- ŚWIADOMA GRANICA: token wchodzi do CHECK-a RAZEM z kolumną, choć pisarza dostaje dopiero
-- w `stacks._plan`. Rozdzielenie tego na dwie migracje dałoby stan pośredni, w którym kod umie
-- powiedzieć powód, a baza go odrzuca — awaria przy pierwszym przebiegu, nie przy wdrożeniu.

CREATE TABLE _integration_input_hold (
    integration_id INTEGER,
    input_frame_id INTEGER,
    asserted_by    TEXT,
    excluded       INTEGER
);
INSERT INTO _integration_input_hold (integration_id, input_frame_id, asserted_by, excluded)
    SELECT integration_id, input_frame_id, asserted_by, excluded FROM integration_input;
DROP TABLE integration_input;

CREATE TABLE integration_new (
    id                INTEGER PRIMARY KEY,
    master_frame_id   INTEGER NOT NULL UNIQUE REFERENCES frame (id),
    integ_hash        TEXT,
    created_at        TEXT    NOT NULL,
    updated_at        TEXT,
    tool              TEXT,
    window_start      TEXT,
    window_end        TEXT,
    declared_rows     INTEGER,
    drizzle_inputs    INTEGER,
    disabled_inputs   INTEGER,
    degenerate        INTEGER NOT NULL DEFAULT 0,
    ambiguous         INTEGER NOT NULL DEFAULT 0,
    telescope_mismatch INTEGER NOT NULL DEFAULT 0,
    utc_offset_min    INTEGER,                 -- trójstan: NULL nieznane | 0 UTC | minuty (R2)
    unresolved_reason TEXT
        CHECK (unresolved_reason IS NULL OR unresolved_reason IN (
            'degenerate_window', 'history_mismatch', 'no_object', 'no_window', 'no_candidates',
            'telescope_mismatch', 'offset_unknown'))
);

-- KOMPLET KOLUMN, wypisany jawnie po obu stronach (nie `SELECT *`): kolejność kolumn tabeli
-- źródłowej jest faktem historycznym, a nie kontraktem — jawna lista przeżyje każdą przyszłą
-- przebudowę, a `*` przy pierwszej rozjeżdżałby wartości między kolumny po cichu.
INSERT INTO integration_new (
    id, master_frame_id, integ_hash, created_at, updated_at, tool, window_start, window_end,
    declared_rows, drizzle_inputs, disabled_inputs, degenerate, ambiguous, telescope_mismatch,
    unresolved_reason)
    SELECT id, master_frame_id, integ_hash, created_at, updated_at, tool, window_start, window_end,
           declared_rows, drizzle_inputs, disabled_inputs, degenerate, ambiguous, telescope_mismatch,
           unresolved_reason FROM integration;

DROP TABLE integration;
ALTER TABLE integration_new RENAME TO integration;

-- Dziecko wraca ZE SWOIM źródłem i swoim `excluded` — inaczej migracja skasowałaby werdykty ręki
-- (`excluded=1`) i zdegradowała dowiedzione `history` do `window`. 0012 mogła wstawić stałą
-- `'window'`, bo kopiowała zero wierszy z tabeli bez tej kolumny; tu wierszy są tysiące.
CREATE TABLE integration_input (
    integration_id INTEGER NOT NULL REFERENCES integration (id),
    input_frame_id INTEGER NOT NULL REFERENCES frame (id),
    asserted_by    TEXT    NOT NULL CHECK (asserted_by IN ('history', 'window', 'user')),
    excluded       INTEGER NOT NULL DEFAULT 0,
    UNIQUE (integration_id, input_frame_id)
);

INSERT INTO integration_input (integration_id, input_frame_id, asserted_by, excluded)
    SELECT integration_id, input_frame_id, asserted_by, excluded FROM _integration_input_hold;

DROP TABLE _integration_input_hold;

CREATE INDEX idx_integration_input_frame ON integration_input (input_frame_id);

PRAGMA user_version = 16;
