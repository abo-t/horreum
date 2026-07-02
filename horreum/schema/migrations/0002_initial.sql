-- Horreum — migracja 0002: schemat rdzenia po przejściu fitsmirror (PF-2).
-- Źródło prawdy: brief/PLAN_przejscie_fits.md §2/§3/§8 (v1.3). Czas = ISO-8601 TEXT.
-- Wszystkie zapisy domenowe przez repository layer (horreum.repo) → event.
-- Zastępuje 0001 (rename, D-A/R2#12): świeża baza startuje od razu w v2; przedpotopowa
-- baza v1 dostaje jawny błąd w runnerze (db.migrate), nie cichą pół-migrację.

-- ============================================================ 1.1 tożsamość i lokalizacja

-- frame: tożsamość = odcisk sekcji DANYCH (przeżywa edycję nagłówka/rename/move/writeback).
-- Interpretacje (config/object/filter) jako FK/pola. Fakty KOPII pliku mieszkają na location.
CREATE TABLE frame (
    id            INTEGER PRIMARY KEY,
    sha1_data     TEXT    NOT NULL UNIQUE,   -- sha1 sekcji danych HDU / attachmentu XISF
    sha1_data_uncomputable INTEGER NOT NULL DEFAULT 0,  -- 1 = degeneracja: to sha1 CAŁEGO pliku
    kind          TEXT    NOT NULL,          -- light|flat|dark|bias|master_*|unknown
    filetype      TEXT,                      -- fits|xisf|dng|raw_sony|raw_canon
    camera_id     INTEGER REFERENCES camera(id),     -- oś KAMERA (deterministyczna przy skanie)
    config_id     INTEGER REFERENCES config(id),     -- iloczyn osi (po grupowaniu; NULL => review)
    object_id     INTEGER REFERENCES object(id),     -- oś OBIEKT (NULL => review)
    object_source TEXT,                       -- header|alias|catalog_xref|review|user
    filter_canon  TEXT,                       -- oś FILTR znormalizowana (Ha|OIII|L-Pro|...); NULL => review
    first_seen_at TEXT    NOT NULL
);
-- INWARIANT (test): jeśli config_id NOT NULL, to config.camera_id == frame.camera_id.

-- location: GDZIE plik leży + fakty KOPII (writeback `os.replace` zmienia bajty pliku,
-- nie zmieniając tożsamości frame'a — R2#6). frame 1:N location.
CREATE TABLE location (
    id               INTEGER PRIMARY KEY,
    frame_id         INTEGER NOT NULL REFERENCES frame(id),
    volume           TEXT    NOT NULL,        -- TRWAŁY identyfikator wolumenu (serial/UUID; §7.5)
    drive_letter     TEXT,                    -- efemeryczny cache wyświetlania (R:) — NIE tożsamość
    path             TEXT    NOT NULL,        -- pełna ścieżka (forma LITEROWA, nigdy UNC)
    tier             TEXT,                    -- cold|scratch
    mtime            TEXT,                    -- brama przyrostowa (volume, path, mtime)
    file_sha1        TEXT,                    -- sha1 całego pliku (detekcja zmiany bajtów)
    header_hash      TEXT,                    -- sha1 tekstu nagłówka (kontrola writeback/undo; NULL dla XISF)
    hdu_index        INTEGER,                 -- HDU naukowe (NULL dla XISF)
    compressed       INTEGER,                 -- 0/1 CompImageHDU (NULL dla XISF)
    size_bytes       INTEGER,                 -- fakt kopii (przeniesione z frame — R2#6)
    present          INTEGER NOT NULL DEFAULT 1,   -- 1=plik jest, 0=zniknął z tej ścieżki
    last_verified_at TEXT,
    UNIQUE(volume, path)
);

-- ============================================================ 1.2 nagłówek (zeznanie 1:1)

-- header: warstwa faktów. raw_json = źródło prawdy nagłówkowej; pola gorące wyłuskane.
-- Zeznanie odświeża OSTATNI re-odczyt (last-read-wins przy zmianie header_hash — brief §2).
CREATE TABLE header (
    frame_id            INTEGER PRIMARY KEY REFERENCES frame(id),
    raw_json            TEXT NOT NULL,         -- pełny nagłówek FITS jako json
    date_obs            TEXT,
    exptime             REAL,
    filter_raw          TEXT,                  -- surowy FILTER (przed normalizacją)
    instrume            TEXT,
    telescop            TEXT,                  -- surowy TELESCOP (canon = strip w osi)
    focallen            REAL,                  -- ogniskowa (mm)
    focratio_raw        REAL,                  -- surowy FOCRATIO (audyt; normalizacja MARTWA po naprawie nagłówków)
    xpixsz              REAL,                  -- właściwość kamery (uzupełnia upsert_camera)
    ypixsz              REAL,                  -- sanity: == xpixsz
    gain                TEXT,                  -- USTAWIENIE akwizycji (audyt, NIE tożsamość)
    offset_adu          INTEGER,               -- USTAWIENIE ('offset' = słowo zarezerwowane)
    ccd_temp            REAL,                  -- USTAWIENIE
    usblimit            INTEGER,               -- USTAWIENIE
    xbinning            INTEGER,
    ybinning            INTEGER,
    bayerpat            TEXT,                  -- OBECNY => kolor (OSC). Reguła jednokierunkowa (§3.2)
    ra_deg              REAL,
    dec_deg             REAL,
    object_raw          TEXT                   -- nazwa obiektu jak w nagłówku ("plotka")
);

-- cards: pełne lustro nagłówka FITS (EAV, wg fitsmirror db.py:40-52). `idx` numeruje
-- wystąpienia keyworda (duplikaty COMMENT/HISTORY i powtórzone keywordy wiernie).
CREATE TABLE cards (
    frame_id   INTEGER NOT NULL REFERENCES frame(id),
    keyword    TEXT NOT NULL,
    idx        INTEGER NOT NULL DEFAULT 0,
    value_raw  TEXT,
    value_num  REAL,
    value_type TEXT,                           -- int|float|str|bool|undefined
    comment    TEXT,
    PRIMARY KEY (frame_id, keyword, idx)
);
CREATE INDEX idx_cards_kw_num ON cards(keyword, value_num);
CREATE INDEX idx_cards_kw_raw ON cards(keyword, value_raw);

-- ============================================================ 1.3 osie hardware

-- camera: oś KAMERA. Tożsamość = model_canon (po naprawie nagłówków INSTRUME 100%, 5 form).
-- pixel_um = NULLABLE właściwość (uzupełnia upsert_camera CAS-em); rozjazd wartości = STAN
-- pixel_conflict (kolejka ze stanu, nie z count(event)).
CREATE TABLE camera (
    id             INTEGER PRIMARY KEY,
    model_canon    TEXT NOT NULL UNIQUE,      -- ASI2600MM|ASI2600MD|ASI2600MC|ASI294MC|SONYA7RM3
    pixel_um       REAL,                      -- właściwość; uzupełnia upsert_camera + event
    pixel_conflict INTEGER NOT NULL DEFAULT 0,-- 1 = rozjazd wartości piksela (review ze stanu)
    is_mono        INTEGER,                   -- 1 mono | 0 kolor | NULL nierozstrzygnięte
    is_mono_source TEXT,                       -- bayerpat|model|raw_format|review
    raw_instrume   TEXT,                       -- ostatni surowy INSTRUME (audyt)
    created_at     TEXT NOT NULL
);

-- telescope: oś TELESKOP. Tożsamość = telescop_canon = TELESCOP.strip() (po naprawie nagłówków
-- TELESCOP 100%, 8 nazw × 1 ogniskowa). NOCASE = bezpiecznik 'RC8 '/'rc8' (ASCII — świadome);
-- casing wyświetlany = pierwszego wystąpienia. f/ i ogniskowa to WŁAŚCIWOŚCI (nullable), nie klucz.
CREATE TABLE telescope (
    id               INTEGER PRIMARY KEY,
    telescop_canon   TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    label            TEXT,                     -- etykieta usera; NULL => niezatwierdzony
    f_ratio_nominal  REAL,                     -- właściwość (audyt/wyświetlanie)
    focal_nominal    INTEGER,                  -- właściwość (audyt/wyświetlanie)
    status           TEXT    NOT NULL,         -- proposed|approved
    merged_into      INTEGER REFERENCES telescope(id),   -- gdy user scali; NULL => kanoniczny
    created_at       TEXT    NOT NULL
);

-- ============================================================ 1.4 konfiguracja (iloczyn osi)

-- config: iloczyn (telescope × camera). Wyłania się ze skanu jako realnie występująca para.
CREATE TABLE config (
    id           INTEGER PRIMARY KEY,
    telescope_id INTEGER NOT NULL REFERENCES telescope(id),
    camera_id    INTEGER NOT NULL REFERENCES camera(id),
    label        TEXT,                          -- etykieta usera (opcjonalna); NULL => auto
    status       TEXT NOT NULL,                 -- proposed|approved
    created_at   TEXT NOT NULL,
    UNIQUE(telescope_id, camera_id)
);
-- Scalanie na OSI (telescope.merged_into); config liczony na canonical (widok niżej).

-- ============================================================ 1.5 obiekt (oś)

CREATE TABLE object (
    id      INTEGER PRIMARY KEY,
    canon   TEXT NOT NULL UNIQUE,               -- NGC4258|Sh2-131|Moon|C/2025 A6 (Lemmon)
    catalog TEXT,                               -- NGC|IC|Sh2|Messier|solar|comet
    kind    TEXT                                -- deep_sky|solar_system|comet
);

CREATE TABLE object_alias (
    id         INTEGER PRIMARY KEY,
    alias_norm TEXT NOT NULL UNIQUE,            -- znormalizowana forma (bez spacji, lower)
    object_id  INTEGER NOT NULL REFERENCES object(id),
    source     TEXT NOT NULL                    -- catalog_xref|common_name|header|review|user
);

-- ============================================================ 1.6 audyt, kolekcje

-- event: append-only audyt + time-travel. Repository layer emituje TU każdą zmianę.
CREATE TABLE event (
    id      INTEGER PRIMARY KEY,
    ts      TEXT NOT NULL,
    actor   TEXT NOT NULL,                      -- scan|resolver|grouper|user:<id>|import:fitsmirror
    verb    TEXT NOT NULL,
    target  TEXT NOT NULL,                      -- frame:<id>|sha1:<sha1>|telescope:<id>|location:<id>|...
    payload TEXT,                               -- json (before/after)
    reason  TEXT
);

CREATE TABLE saved_query (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE,
    sql_text   TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- ============================================================ 1.7 szkielet na przyszłość (PUSTY)

-- calibration: light <-> master (dark/flat). Relacja JAWNA, nie z parsowania nazw.
CREATE TABLE calibration (
    id              INTEGER PRIMARY KEY,
    light_frame_id  INTEGER REFERENCES frame(id),
    master_frame_id INTEGER REFERENCES frame(id),
    relation        TEXT,                       -- dark|flat|bias
    asserted_by     TEXT,                       -- user|wbpp|heuristic
    confidence      TEXT
);

-- integration + integration_input: lineage masterlighta (DAG "co weszło w stack").
CREATE TABLE integration (
    id              INTEGER PRIMARY KEY,
    master_frame_id INTEGER REFERENCES frame(id),  -- powstały masterlight
    integ_hash      TEXT,                       -- hash zestawu wejść
    created_at      TEXT,
    tool            TEXT                        -- WBPP|...
);
CREATE TABLE integration_input (
    integration_id INTEGER REFERENCES integration(id),
    input_frame_id INTEGER REFERENCES frame(id)     -- sub/master, który wszedł w stack
);

-- ============================================================ widoki

-- telescope_canonical: rozwiązanie łańcucha merged_into (§3.6). Config liczony na canonical.
CREATE VIEW telescope_canonical AS
WITH RECURSIVE chain(id, canon_id) AS (
    SELECT id, COALESCE(merged_into, id) FROM telescope WHERE merged_into IS NULL
    UNION ALL
    SELECT t.id, c.canon_id FROM telescope t JOIN chain c ON t.merged_into = c.id
)
SELECT id, canon_id FROM chain;

-- indeksy wspierające skan/raporty
CREATE INDEX idx_location_frame ON location(frame_id);
CREATE INDEX idx_frame_camera   ON frame(camera_id);
CREATE INDEX idx_frame_config   ON frame(config_id);
CREATE INDEX idx_event_target   ON event(target);
