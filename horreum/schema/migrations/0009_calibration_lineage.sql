-- Horreum — migracja 0009: RODOWÓD light↔master (segment C4, #6).
-- Źródło prawdy: brief/PLAN_kalibracja_C4_brief.md (v1 po recenzji adwersaryjnej, D-C-4-a wariant A).
--
-- PRZEBUDOWA tabeli `calibration` (wzorzec 0007): tabela istnieje jako PUSTY szkielet od 0002
-- (recenzent potwierdził read-only: zero DML domenowego dziś), więc INSERT SELECT kopiuje 0 wierszy.
-- Cel przebudowy: dołożyć kontrakt, którego szkielet nie miał —
--   * NOT NULL na `light_frame_id`, `master_frame_id`, `relation` (relacja bez którejś strony jest bez sensu),
--   * CHECK `relation IN ('dark','bias','flat')` (klasa kalibratora = `recipe_class` po zdjęciu `master_`),
--   * UNIQUE(light_frame_id, relation) — „jeden kalibrator danej klasy na light".
--     To ON, nie kod, jest strażnikiem idempotencji: `repo.link_calibration` robi UPDATE po tym kluczu,
--     a nie mnoży wierszy. Wariant „tylko guard w kodzie" odrzucony (D-C-4-a): inwariant jako kontrakt DB.
--
-- SQLite nie dokłada UNIQUE/NOT NULL ALTER-em → CREATE new + INSERT SELECT + DROP + RENAME.
-- Żaden indeks nie istniał na `calibration` (0002 go nie tworzył), więc nie ma czego odtwarzać;
-- UNIQUE zakłada własny indeks. Nic nie odwołuje się FK-em DO `calibration`, więc DROP jest bezpieczny.
CREATE TABLE calibration_new (
    id              INTEGER PRIMARY KEY,
    light_frame_id  INTEGER NOT NULL REFERENCES frame (id),
    master_frame_id INTEGER NOT NULL REFERENCES frame (id),
    relation        TEXT    NOT NULL CHECK (relation IN ('dark', 'bias', 'flat')),
    asserted_by     TEXT    NOT NULL,           -- 'horreum' (wyliczone z przepisu); user/wbpp przebijają
    confidence      TEXT,                       -- 'recipe' (dopasowanie po przepisie — jedyna droga C4)
    UNIQUE (light_frame_id, relation)
);

INSERT INTO calibration_new (id, light_frame_id, master_frame_id, relation, asserted_by, confidence)
    SELECT id, light_frame_id, master_frame_id, relation, asserted_by, confidence FROM calibration;

DROP TABLE calibration;
ALTER TABLE calibration_new RENAME TO calibration;

CREATE INDEX idx_calibration_light  ON calibration (light_frame_id);
CREATE INDEX idx_calibration_master ON calibration (master_frame_id);

PRAGMA user_version = 9;
