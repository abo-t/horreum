-- 0042 - KOD POWODU WARSTWY PISARZA KARTY I RENAMU (AR-148): powód wpisu stagingu karty
-- (`pending_changes.reason`), renamu (`pending_renames.reason`) i zapisu wstrzymanego
-- (`withheld_write.reason`) leżał wyłącznie jako polska proza, a rdzeń czyta go z bazy do zdań okien
-- (uwaga dokończenia zapisu w miejscu, wynik zeznania wstrzymanego, karta z poprzedniej próby, nota
-- cofnięcia gestu). Obok prozy wchodzi KOD i PARAMETRY (wzorzec 0041); okno składa z nich zdanie
-- w języku UI (`objchg.item.<kod>`), proza zostaje dla CLI, logu i wierszy bez kodu.
--
-- PRZYROST (ADD COLUMN) - zero przebudowy, zero ruszonych wierszy, BEZ backfillu: na żywym archiwum
-- powód ma 1 z 8683 wpisów kart, 63 z 502 wpisów renamu (62 × „cofnięto (undo)”) i 1 z 1 wstrzymań
-- (sonda 2026-10-15, `?mode=ro`). Zgadywanie kodu z prozy byłoby drugim parserem dawnych zdań.
-- Wiersz z kodem NULL = proza jak dotąd.
--
-- TRÓJKĘ `reason`/`reason_code`/`reason_args` piszą WYŁĄCZNIE `repo._set_pending_reason_tx`,
-- `repo._set_rename_reason_tx` i INSERT w `repo._withhold_write_tx` (kodek `item_reasons.do_bazy`,
-- meta-test AST). Powód odmowy rekoncyliacji zamiaru renamu (`repo.note_rename_intent_refusal`, AR-323)
-- idzie tą samą drogą - przez `repo._set_rename_reason_tx`.
--
-- STRAŻNIK W DDL (wzorzec 0041): kod nigdy bez prozy, parametry wyłącznie razem z kodem i zawsze jako
-- obiekt JSON. `withheld_write.reason` jest `NOT NULL` od 0037 - tam „kod tylko z prozą” trzyma
-- tamten CHECK.
ALTER TABLE pending_changes ADD COLUMN reason_code TEXT
    CHECK (reason_code IS NULL OR (length(reason_code) > 0 AND reason IS NOT NULL));
ALTER TABLE pending_changes ADD COLUMN reason_args TEXT
    CHECK ((reason_args IS NULL) = (reason_code IS NULL)
           AND (reason_args IS NULL
                OR (json_valid(reason_args) AND json_type(reason_args) = 'object')));
ALTER TABLE pending_renames ADD COLUMN reason_code TEXT
    CHECK (reason_code IS NULL OR (length(reason_code) > 0 AND reason IS NOT NULL));
ALTER TABLE pending_renames ADD COLUMN reason_args TEXT
    CHECK ((reason_args IS NULL) = (reason_code IS NULL)
           AND (reason_args IS NULL
                OR (json_valid(reason_args) AND json_type(reason_args) = 'object')));
ALTER TABLE withheld_write ADD COLUMN reason_code TEXT
    CHECK (reason_code IS NULL OR length(reason_code) > 0);
ALTER TABLE withheld_write ADD COLUMN reason_args TEXT
    CHECK ((reason_args IS NULL) = (reason_code IS NULL)
           AND (reason_args IS NULL
                OR (json_valid(reason_args) AND json_type(reason_args) = 'object')));
