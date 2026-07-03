-- Horreum — migracja 0004: oś OBSERWATORIUM (PLAN_os_obserwatorium §3).
-- PRZYROST nad 0003: nowa tabela observatory + frame.observatory_id + widok observatory_canonical.
-- Zero zmian istniejących tabel poza ALTER ADD COLUMN (re-skan/resolve wypełnia — D3: nie konwerter).
-- Tożsamość osi = GEOMETRIA (proximity-match ≤ THRESH_KM w repo.propose_observatory), NIE string:
-- name = etykieta usera (NIE klucz), seed lat/lon ZAMROŻONY przy utworzeniu (§2b/D4). Bez approve
-- w v1 (port osi = merge+unmerge+label); status zostaje 'proposed'.

CREATE TABLE observatory (
    id          INTEGER PRIMARY KEY,
    name        TEXT,                       -- etykieta usera (NIE tożsamość); NULL => nienazwane
    lat         REAL NOT NULL,              -- seed stanowiska ZAMROŻONY przy utworzeniu (§2b/D4)
    lon         REAL NOT NULL,              -- seed; stopnie dziesiętne (parse_coord znormalizował)
    elev        REAL,                       -- SITEELEV = atrybut, nie tożsamość (D3); nullable
    merged_into INTEGER REFERENCES observatory(id),   -- gdy user scali; NULL => kanoniczny
    status      TEXT NOT NULL,              -- proposed (approve poza v1)
    created_at  TEXT NOT NULL
);

-- Oś na frame (NULL => brak GPS albo GPS nieparsowalny — review ze STANU, jak camera-review; D5).
ALTER TABLE frame ADD COLUMN observatory_id INTEGER REFERENCES observatory(id);

-- observatory_canonical: rozwiązanie łańcucha merged_into (kopia telescope_canonical 0002:197-203).
-- Licznik klatek liczony na canonical (widok queries.active_observatories); głębokość ≤ 1 (gwardy merge).
CREATE VIEW observatory_canonical AS
WITH RECURSIVE chain(id, canon_id) AS (
    SELECT id, COALESCE(merged_into, id) FROM observatory WHERE merged_into IS NULL
    UNION ALL
    SELECT o.id, c.canon_id FROM observatory o JOIN chain c ON o.merged_into = c.id
)
SELECT id, canon_id FROM chain;

CREATE INDEX idx_frame_observatory ON frame(observatory_id);
