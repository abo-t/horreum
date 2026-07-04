-- Horreum — migracja 0005: staging hurtowego renamu ("Nazwy z faktów", trzecia operacja klingi).
-- Źródło prawdy: brief/PLAN_nazwy_z_faktow.md §3/§5-D5. PRZYROST nad 0004 (ADD tabeli, zero zmian
-- istniejących). Zapis stagingu przez repository layer (horreum.repo); mutacja plików = horreum.writeback
-- (`os.rename`). Osobna tabela od `pending_changes` (D5): inny kształt (path→path) I inna kotwica
-- (`mtime`+cel-nieistnieje, NIE `header_hash` — NULL dla XISF, a rename DZIAŁA dla XISF); COHESION.

-- pending_renames: podgląd renamu (compose_name z faktów) PRZED mutacją plików. Kluczowane
-- location_id (rename rusza JEDEN fizyczny plik; tożsamość frame `sha1_data` przeżywa — rename nie
-- tyka bajtów). Transient bookkeeping: NIE emituje eventu per wiersz (event = fakt domenowy =
-- `location.renamed`, emitowany przez `repo.relocate_location` przy commicie). `expected_mtime` =
-- mtime location w chwili STAGINGU (kotwica anty-stale: commit odrzuca, gdy plik zmienił się od
-- podglądu). Wiersz 'applied' SAM jest rekordem undo (old_path/new_path) — bez osobnej tabeli commitów.
CREATE TABLE pending_renames (
    id             INTEGER PRIMARY KEY,
    run_id         TEXT NOT NULL,
    location_id    INTEGER NOT NULL REFERENCES location(id),   -- fizyczny plik (nie frame)
    old_path       TEXT NOT NULL,
    new_path       TEXT NOT NULL,
    expected_mtime TEXT,                         -- mtime location przy stagingu (kotwica anty-stale)
    status         TEXT NOT NULL DEFAULT 'pending'
                   CHECK (status IN ('pending', 'applied', 'failed', 'skipped', 'blocked')),
    reason         TEXT
);
CREATE INDEX idx_prenames_run ON pending_renames (run_id, status);
CREATE INDEX idx_prenames_loc ON pending_renames (location_id);
