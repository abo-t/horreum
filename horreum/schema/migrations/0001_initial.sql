-- Horreum — migracja 0001: schemat rdzenia plastra B (model osi).
-- Źródło prawdy: brief/PLAN_horreum_schema.md §1 (v2.1). Czas = ISO-8601 TEXT.
-- Wszystkie zapisy domenowe przez repository layer (horreum.repo) → event (§2).

-- ============================================================ 1.1 tożsamość i lokalizacja

-- frame: tożsamość pliku. Klucz logiczny = sha1. Interpretacje (config/object/filter) jako FK/pola.
CREATE TABLE frame (
    id            INTEGER PRIMARY KEY,
    sha1          TEXT    NOT NULL UNIQUE,   -- pełny sha1 (tożsamość)
    kind          TEXT    NOT NULL,          -- light|flat|dark|bias|master_*|unknown
    filetype      TEXT,                      -- fits|xisf|dng|raw_sony|raw_canon
    size_bytes    INTEGER,
    camera_id     INTEGER REFERENCES camera(id),     -- oś KAMERA (deterministyczna przy skanie)
    config_id     INTEGER REFERENCES config(id),     -- iloczyn osi (po grupowaniu; NULL => review)
    object_id     INTEGER REFERENCES object(id),     -- oś OBIEKT (NULL => review)
    object_source TEXT,                       -- header|alias|catalog_xref|review|user
    filter_canon  TEXT,                       -- oś FILTR znormalizowana (Ha|OIII|L-Pro|...); NULL => review
    first_seen_at TEXT    NOT NULL
);
-- INWARIANT (test): jeśli config_id NOT NULL, to config.camera_id == frame.camera_id.

-- location: GDZIE plik leży. frame 1:N location.
CREATE TABLE location (
    id               INTEGER PRIMARY KEY,
    frame_id         INTEGER NOT NULL REFERENCES frame(id),
    volume           TEXT    NOT NULL,        -- TRWAŁY identyfikator wolumenu (serial/UUID/UNC; §7.5)
    drive_letter     TEXT,                    -- efemeryczny cache wyświetlania (R:) — NIE tożsamość
    path             TEXT    NOT NULL,        -- pełna ścieżka (względem wolumenu)
    tier             TEXT,                    -- cold|scratch
    mtime            TEXT,                    -- (klucz przyszłego cache sha1, §7.9)
    present          INTEGER NOT NULL DEFAULT 1,   -- 1=plik jest, 0=zniknął z tej ścieżki
    last_verified_at TEXT,
    UNIQUE(volume, path)
);

-- ============================================================ 1.2 nagłówek (zeznanie 1:1)

-- header: warstwa faktów. raw_json = źródło prawdy nagłówkowej; pola gorące wyłuskane.
-- Trzyma nagłówek FITS (plaster B). DSLR/EXIF = osobny moduł/ścieżka (§4).
CREATE TABLE header (
    frame_id            INTEGER PRIMARY KEY REFERENCES frame(id),
    raw_json            TEXT NOT NULL,         -- pełny nagłówek FITS jako json
    date_obs            TEXT,
    exptime             REAL,
    filter_raw          TEXT,                  -- surowy FILTER (przed normalizacją)
    instrume            TEXT,
    telescop            TEXT,                  -- surowy (brudny: teleskop|montaż|śmieci)
    focallen            REAL,                  -- ogniskowa (mm) — czysta optyka
    focratio_raw        REAL,                  -- surowy FOCRATIO (bywa = apertura)
    focratio_norm       REAL,                  -- f/ po normalizacji (§3.3)
    focratio_norm_src   TEXT,                  -- ok|recovered|review (ślad reguły)
    xpixsz              REAL,                  -- część tożsamości kamery (rozróżnia MODELE, §3.1)
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

-- ============================================================ 1.3 osie hardware

-- camera: oś KAMERA. Tożsamość = (model_canon, pixel_um).
-- pixel_um ROZRÓŻNIA MODELE (firsthand: 2600=3.76, ASI294=4.63, Sony-FITS=4.86) — realny
-- dyskryminator. model_canon rozróżnia warianty w obrębie modelu (MM/MC/MD przy 3.76).
CREATE TABLE camera (
    id             INTEGER PRIMARY KEY,
    model_canon    TEXT NOT NULL,             -- ASI2600MM|ASI2600MD|ASI2600MC|ASI294MC|...
    pixel_um       REAL NOT NULL,             -- XPIXSZ (część tożsamości)
    is_mono        INTEGER,                   -- 1 mono | 0 kolor | NULL nierozstrzygnięte
    is_mono_source TEXT,                       -- bayerpat|model|raw_format|review
    raw_instrume   TEXT,                       -- ostatni surowy INSTRUME (audyt)
    created_at     TEXT NOT NULL,
    UNIQUE(model_canon, pixel_um)
);

-- telescope: oś TELESKOP. Sygnatura = (f_ratio_nominal, focal_nominal) = centroid grupy.
CREATE TABLE telescope (
    id               INTEGER PRIMARY KEY,
    label            TEXT,                     -- etykieta usera (A140R|ED120|RC8...); NULL => niezatwierdzony
    f_ratio_nominal  REAL    NOT NULL,         -- centroid f/ (po normalizacji FOCRATIO)
    focal_nominal    INTEGER NOT NULL,         -- centroid ogniskowej (mm)
    status           TEXT    NOT NULL,         -- proposed|approved
    merged_into      INTEGER REFERENCES telescope(id),   -- gdy user scali; NULL => kanoniczny
    telescop_hint    TEXT,                     -- reprezentatywny surowy TELESCOP (audyt)
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
    actor   TEXT NOT NULL,                      -- scan|resolver|grouper|user:<id>|import-legacy
    verb    TEXT NOT NULL,
    target  TEXT NOT NULL,                      -- frame:<sha1>|telescope:<id>|object:<canon>|...
    payload TEXT,                               -- json (before/after)
    reason  TEXT
);

CREATE TABLE saved_query (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE,
    sql_text   TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- ============================================================ 1.7 szkielet na przyszłość (PUSTY w plastrze B)

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
