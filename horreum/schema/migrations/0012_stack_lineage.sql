-- Horreum — migracja 0012: RODOWÓD GOTOWYCH STOSÓW (segment I-2c, paczka P-I).
-- Źródło prawdy: brief/PLAN_pi_martwe_tabele.md §4 (v2 po recenzji trzema silnikami; D-P-I-2/6).
--
-- PRZEBUDOWA obu tabel szkieletu z 0002 (`integration`, `integration_input`) — wzorzec 0007/0009.
-- Obie dowodnie PUSTE (fakt 1 briefu: zero wierszy, zero pisarzy w `repo.py`), więc INSERT SELECT
-- kopiuje 0 wierszy; przebudowa dokłada kontrakt, którego szkielet nie miał, a nie migruje danych.
--
-- CO ZMIENIA SIĘ MERYTORYCZNIE WOBEC SZKIELETU (i dlaczego — każdy punkt to zmierzone znalezisko):
--
-- 1. TOŻSAMOŚĆ INTEGRACJI STOI NA KLATCE MASTERA, nie na zbiorze wejść (§4.1, S4/K3/F2).
--    Szkielet sugerował `integ_hash` = „hash zestawu wejść". Gdyby był kluczem, doskan dokładający
--    jedną klatkę w oknie dawałby INNY hash → DRUGI wiersz o tej samej integracji, wprost przeciwko
--    bramce idempotencji. Kluczem jest więc UNIQUE(master_frame_id) — tożsamość treści pliku
--    (`frame.sha1_data`) repo już zna. `integ_hash` ZOSTAJE, ale w roli ODCISKU BIEŻĄCEGO
--    DOPASOWANIA (fakt o wyliczeniu, nie klucz): jego zmiana uruchamia reconcile, nie tworzy bytu.
--
-- 2. RELACJA MA TRZY STANY (§4.2, D-P-I-2 wariant B): `history` (plik zeznał wprost i test
--    ZAWIERANIA przeszedł), `window` (KANDYDAT z okna czasu — wyliczony, nie dowiedziony),
--    `user` (człowiek rozstrzygnął). Precedencja user > history > window, lustro osi kalibracji.
--    Kandydat nigdy nie udaje faktu — dlatego CHECK jest w BAZIE, nie w komentarzu.
--    `excluded` niesie odrzucenie ręką (I-2d): usera nie kasujemy, jego „nie" jest faktem.
--
-- 3. WIERSZ INTEGRACJI POWSTAJE TAKŻE WTEDY, GDY WEJŚĆ NIE ZNAMY. `unresolved_reason` mówi
--    dlaczego (okno zdegenerowane — 23 z 84 masterów starszego rocznika; rozjazd z historią;
--    brak obiektu/okna/kandydatów). Cicha nieprawda jest gorsza niż brak odpowiedzi: taki stos
--    ma być WIDOCZNY jako „nie wiem", a nie wyglądać jak stos z jednym subem.
--
-- 4. FAKTY HISTORII SIEDZĄ NA INTEGRACJI, NIE NA WEJŚCIU (K6/K8 po korekcie). Ścieżki z historii
--    są martwe dla dopasowania po nazwie (zmierzone 0/36: historia wskazuje dysk roboczy i nazwy
--    WBPP, archiwum trzyma nazwy z akwizycji), więc `drizzlePath`/`enabled` NIE dają się przypiąć
--    do konkretnej klatki archiwum. Ich prawdziwym nosicielem jest integracja: `declared_rows`,
--    `drizzle_inputs`, `disabled_inputs`. Kolumna per-wejście, której nie da się uczciwie
--    wypełnić, nie powstaje.
--
-- SQLite nie dokłada UNIQUE/NOT NULL ALTER-em → CREATE new + INSERT SELECT + DROP + RENAME.
-- Żaden indeks nie istniał na tych tabelach (0002 ich nie tworzył), więc nie ma czego odtwarzać.
--
-- KOLEJNOŚĆ WYMUSZA TU FK, nie estetyka (0009 tego problemu nie miał — `calibration` nie ma
-- dziecka): dopóki `integration_input` trzyma wiersz wskazujący `integration`, DROP rodzica leci
-- na `FOREIGN KEY constraint failed` przy `foreign_keys = ON`. Rozwiązanie bez ruszania pragm
-- (migracja nie ma prawa rozbrajać kontraktu, na który reszta bazy liczy): wiersze dziecka
-- przechodzą przez tabelę PRZECHOWALNI bez FK, dziecko znika PRZED rodzicem, a wraca po nim.
-- Na produkcji obie tabele są puste, więc to formalność — ale migracja ma być poprawna dla
-- KAŻDYCH danych, jakie ten schemat mógł wyprodukować sensownie.
--
-- ŚWIADOMA GRANICA TEJ OBIETNICY: 0002 dopuszczało `master_frame_id` NULL i duplikaty (kolumna
-- bez NOT NULL i bez UNIQUE, `0002_initial.sql:185`), a docelowa tabela wymaga obu. Baza z takim
-- wierszem wywali migrację na CONSTRAINT — i ma wywalić. Cichy `GROUP BY`/`WHERE` zgubiłby
-- integracje bez śladu, a to gorsze niż głośna odmowa: dane, których ten szkielet nigdy nie
-- dostał (obie tabele były martwe od 0002), nie zasługują na zgadywanie ich tożsamości.

CREATE TABLE _integration_input_hold (
    integration_id INTEGER,
    input_frame_id INTEGER
);
INSERT INTO _integration_input_hold (integration_id, input_frame_id)
    SELECT integration_id, input_frame_id FROM integration_input;
DROP TABLE integration_input;

CREATE TABLE integration_new (
    id                INTEGER PRIMARY KEY,
    master_frame_id   INTEGER NOT NULL UNIQUE REFERENCES frame (id),   -- TOŻSAMOŚĆ (pkt 1)
    integ_hash        TEXT,                    -- odcisk BIEŻĄCEGO dopasowania (nie klucz!)
    created_at        TEXT    NOT NULL,
    updated_at        TEXT,
    tool              TEXT,                    -- PCL:Signature:Integration (process=…,version=…)
    window_start      TEXT,                    -- DATE-OBS mastera = początek pierwszego suba
    window_end        TEXT,                    -- DATE-END mastera = koniec ostatniego
    declared_rows     INTEGER,                 -- ile wejść DEKLARUJE historia; NULL = historii brak
    drizzle_inputs    INTEGER,                 -- ile wierszy historii niesie drizzlePath
    disabled_inputs   INTEGER,                 -- ile wierszy historii ma enabled="false"
    degenerate        INTEGER NOT NULL DEFAULT 0,  -- okno opisuje JEDNĄ klatkę, nie stos
    ambiguous         INTEGER NOT NULL DEFAULT 0,  -- okno nierozłączne z inną integracją tej półki
    telescope_mismatch INTEGER NOT NULL DEFAULT 0, -- master zeznaje inny teleskop niż klatki okna
    unresolved_reason TEXT                     -- NULL = wejścia zapisane; inaczej POWÓD (pkt 3)
        CHECK (unresolved_reason IS NULL OR unresolved_reason IN (
            'degenerate_window', 'history_mismatch', 'no_object', 'no_window', 'no_candidates',
            'telescope_mismatch'))
);

INSERT INTO integration_new (id, master_frame_id, integ_hash, created_at, tool)
    SELECT id, master_frame_id, integ_hash, COALESCE(created_at, ''), tool FROM integration;

DROP TABLE integration;
ALTER TABLE integration_new RENAME TO integration;

-- Wiersze wracają ze źródłem `window` — NAJSŁABSZYM z trójstanu. Szkielet nie niósł informacji,
-- skąd relacja pochodzi, a migracja nie ma prawa nadać jej pewności, której nikt nie dowiódł;
-- awans do `history`/`user` wymaga zeznania pliku albo ręki, nie skryptu.
CREATE TABLE integration_input (
    integration_id INTEGER NOT NULL REFERENCES integration (id),
    input_frame_id INTEGER NOT NULL REFERENCES frame (id),
    asserted_by    TEXT    NOT NULL CHECK (asserted_by IN ('history', 'window', 'user')),
    excluded       INTEGER NOT NULL DEFAULT 0,     -- 1 = człowiek ODRZUCIŁ kandydata (I-2d)
    UNIQUE (integration_id, input_frame_id)        -- strażnik idempotencji (nie kod — jak 0009)
);

INSERT INTO integration_input (integration_id, input_frame_id, asserted_by)
    SELECT integration_id, input_frame_id, 'window' FROM _integration_input_hold;

DROP TABLE _integration_input_hold;

CREATE INDEX idx_integration_input_frame ON integration_input (input_frame_id);

PRAGMA user_version = 12;
