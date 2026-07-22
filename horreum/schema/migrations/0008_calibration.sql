-- Horreum — migracja 0008: oś KALIBRACJI (przepis klatki sprzętowej) + nośnik faktów (C2, #6).
-- Źródło prawdy: brief/PLAN_kalibracja_C_brief.md (v2 po recenzji adwersaryjnej).
--
-- PRZYROST, nie przebudowa: same CREATE TABLE + ADD COLUMN, zero zmian istniejących tabel.
--
-- 1. `header.set_temp` — NASTAWA temperatury, ODCZYTYWANA z zeznania, NIE kopiowana (D-C-2,
--    decyzja Zdzinia 2026-07-22: „nastawy się nie wylicza — odczytuje się ją z nagłówka,
--    a brak w nagłówku znaczy brak wpisu"). Kolumna GENERATED VIRTUAL nie przechowuje własnych
--    danych: pokazuje to, co stoi w `raw_json` przy każdym odczycie. Skutki, dla których wygrała
--    z kopią-kolumną: (a) nie ma czego backfillować na 15 885 wierszach, (b) wartość NIE MOŻE
--    się zestarzeć po writebacku nagłówka, (c) nie trzeba pamiętać o czterech miejscach
--    (`extract_header`, sygnatura `record_header`, literał INSERT, literał UPDATE w
--    `refresh_location`) — pominięcie któregokolwiek dawało ciche stęchnięcie.
--    CAST(... AS REAL) jest KONIECZNY, nie kosmetyczny: `json_extract` oddaje `-10.0` jako REAL
--    dla FITS-ów i jako TEXT dla XISF-ów (zmierzone: 202 klatki), a bez rzutu ta sama nastawa
--    rozpadłaby się na dwie wartości (pułapka W3, ta sama co przy kamerach).
--    NULL = karty nie ma = BRAK WPISU (mastery: 0/111 — integracja w PixInsight zjada nastawy).
ALTER TABLE header ADD COLUMN set_temp REAL
    GENERATED ALWAYS AS (CAST(json_extract(raw_json, '$."SET-TEMP"') AS REAL)) VIRTUAL;

-- 2. `calibration_profile` — PRZEPIS: klasa równoważności klatek sprzętowych o tych samych
--    nastawach. Master i klatka surowa tej samej nastawy trafiają do TEGO SAMEGO wiersza
--    (przedrostek `master_` schodzi do `recipe_class`) — inaczej rodowód nie miałby czego łączyć.
--
--    `profile_key` jest UNIQUE i NIE MA w nim NULL-i: wszystkie pola swojej klasy są wymagane,
--    a klatka bez kompletu NIE DOSTAJE profilu (zostaje `calibration_profile_id IS NULL`
--    + zbiorczy `calibration.review_summary`). Sentinel typu `~` w kluczu odrzucony świadomie:
--    zlewałby DWA mastery o RÓŻNYCH, nieznanych nastawach w jeden przepis, a UNIQUE by tego nie
--    złapał, bo klucze byłyby równe. Brak faktu ma być widoczny, nie schowany w kluczu.
--
--    Kolumny są NULLABLE mimo tego, bo jedna tabela obsługuje dwie klasy: dark/bias niosą
--    czas+temperaturę+gain+offset, flat niesie teleskop+filtr. CHECK pilnuje kompletu per klasa —
--    to on, a nie NOT NULL, jest tu strażnikiem (NOT NULL nie umie być warunkowe).
CREATE TABLE calibration_profile (
    id            INTEGER PRIMARY KEY,
    profile_key   TEXT    NOT NULL UNIQUE,
    recipe_class  TEXT    NOT NULL CHECK (recipe_class IN ('dark', 'bias', 'flat')),
    camera_id     INTEGER NOT NULL REFERENCES camera (id),
    xbinning      INTEGER NOT NULL,
    exptime       REAL,                       -- dark (bias go nie ma z definicji)
    set_temp_c    INTEGER,                    -- dark, bias — nastawa, nie pomiar
    gain          INTEGER,                    -- dark, bias
    offset_adu    INTEGER,                    -- dark, bias
    telescope_id  INTEGER REFERENCES telescope (id),   -- flat (zależność od optyki jest realna)
    filter_canon  TEXT,                       -- flat; NULL = kamera kolorowa (FAKT, nie luka)
    created_at    TEXT    NOT NULL,
    CHECK (recipe_class != 'dark' OR (exptime IS NOT NULL AND set_temp_c IS NOT NULL
           AND gain IS NOT NULL AND offset_adu IS NOT NULL)),
    CHECK (recipe_class != 'bias' OR (set_temp_c IS NOT NULL AND gain IS NOT NULL
           AND offset_adu IS NOT NULL)),
    CHECK (recipe_class != 'flat' OR telescope_id IS NOT NULL)
);

-- 3. `calibration_fact` — fakt przepisu dla POJEDYNCZEJ klatki. Nośnik precedencji: profil jest
--    współdzielony przez N klatek, więc nie ma w nim gdzie zapisać „dla TEJ klatki gain podał
--    człowiek". Bez tej tabeli ręczne uzupełnienie (C3) nie miałoby dokąd pisać, a następny
--    przebieg derywacji kasowałby wpis.
--
--    Trzyma WYŁĄCZNIE to, czego w nagłówku NIE MA (`source` bez wartości 'header') — fakty
--    nagłówkowe czytamy wprost z `header`, zgodnie z D-C-2. Dzięki temu nie powstaje druga kopia
--    zeznania, która mogłaby się rozjechać z oryginałem.
--
--    Fakt ze ŚCIEŻKI zapisujemy RAZ, przy pierwszym rozpoznaniu — nie re-derywujemy co przebieg.
--    Powód jest praktyczny: rename mastera (oś nazw) usuwa `_G100_O21_10_` ze ścieżki, więc
--    re-derywacja po cichu przepięłaby klatkę do innego przepisu.
--
--    PRECEDENCJA `user` > `header` > `path` (D-C-1): wpis człowieka bije nagłówek, spójnie z osią
--    obiektu (`frame.object_source='user'` pomija drabinę resolwerów).
CREATE TABLE calibration_fact (
    frame_id   INTEGER NOT NULL REFERENCES frame (id),
    key        TEXT    NOT NULL CHECK (key IN ('exptime', 'set_temp_c', 'gain', 'offset_adu',
                                               'xbinning', 'filter_canon', 'telescope_id')),
    value      TEXT,                          -- TEXT, bo fakty są heterogeniczne; rzut przy odczycie
                                              -- tą samą derywacją `_coerce`, co pola nagłówka
    source     TEXT    NOT NULL CHECK (source IN ('user', 'path')),
    actor      TEXT    NOT NULL,
    created_at TEXT    NOT NULL,
    PRIMARY KEY (frame_id, key)
);

-- 4. Wskaźnik osi na klatce — jak `frame.config_id`/`frame.observatory_id`.
--    NULL = brak przepisu: albo rodzaj go nie ma (light), albo brak kompletu faktów (review).
ALTER TABLE frame ADD COLUMN calibration_profile_id INTEGER REFERENCES calibration_profile (id);

CREATE INDEX idx_calibration_fact_frame ON calibration_fact (frame_id);
CREATE INDEX idx_frame_calibration_profile ON frame (calibration_profile_id);

PRAGMA user_version = 8;
