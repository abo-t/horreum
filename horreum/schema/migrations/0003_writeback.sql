-- Horreum — migracja 0003: staging writebacku (KROK 4 scalenia, druga klinga).
-- Źródło prawdy: brief/PLAN_gui_writeback.md §2 (port schematu dawcy fitsmirror db.py:54-107,
-- re-key file_id → location_id). PRZYROST nad 0002 (ADD tabel, zero zmian istniejących).
-- Wszystkie zapisy stagingu przez repository layer (horreum.repo); mutacja plików = horreum.writeback.

-- ============================================================ staging: zmiany oczekujące

-- pending_changes: wynik makra (filtr→oblicz→przypisz) PRZED zapisem do plików. Kluczowane
-- location_id (FIZYCZNY plik — writeback rusza bajty JEDNEJ kopii; tożsamość frame sha1_data
-- przeżywa). Transient bookkeeping: NIE emituje eventu per wiersz (event = fakt domenowy =
-- mutacja pliku, brief §3/R#1). `expected_header_hash` = header_hash location w chwili STAGINGU
-- (kotwica anty-stale: commit odrzuca, gdy tożsamość location zmieniła się od stagingu, R#7).
CREATE TABLE pending_changes (
    id          INTEGER PRIMARY KEY,
    run_id      TEXT NOT NULL,
    location_id INTEGER NOT NULL REFERENCES location(id),   -- fizyczny plik (nie frame)
    keyword     TEXT NOT NULL,
    idx         INTEGER,
    op          TEXT NOT NULL CHECK (op IN ('set', 'add')),
    old_value   TEXT,
    new_value   TEXT,
    new_type    TEXT,
    new_comment TEXT,
    expected_header_hash TEXT,           -- header_hash location przy stagingu (kotwica, R#7)
    status      TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'applied', 'failed', 'skipped', 'blocked')),
    reason      TEXT
);
CREATE INDEX idx_pending_run ON pending_changes (run_id, status);
CREATE INDEX idx_pending_loc ON pending_changes (location_id);

-- ============================================================ commit + backup (undo)

-- commits: JEDEN przebieg writebacku (grupuje pliki do undo). Nie encja osiowa — wskaźnik
-- grupujący; audyt mutacji pliku niosą eventy location.refreshed/header.refreshed (actor=user:local).
CREATE TABLE commits (
    id         INTEGER PRIMARY KEY,
    run_id     TEXT NOT NULL,
    applied_at TEXT,
    summary    TEXT
);
CREATE INDEX idx_commits_run ON commits (run_id);

-- header_backups: pełny nagłówek HDU SPRZED commitu → undo przepisuje go z powrotem (obsługuje
-- set I add BEZ operacji delete). `post_hash` = header_hash PO commicie: kontrola undo (plik
-- zmieniony od naszego commitu → undo blocked). UNIQUE(commit_id, location_id): jeden backup na
-- plik na commit. Append-only: nigdy nie kasowane (historia undo). Kluczowane location_id.
CREATE TABLE header_backups (
    id          INTEGER PRIMARY KEY,
    commit_id   INTEGER NOT NULL REFERENCES commits (id),
    location_id INTEGER NOT NULL REFERENCES location(id),
    hdu_index   INTEGER NOT NULL,
    header_text TEXT NOT NULL CHECK (length(header_text) > 0),
    post_hash   TEXT NOT NULL,
    UNIQUE (commit_id, location_id)
);
CREATE INDEX idx_header_backups_commit ON header_backups (commit_id);

-- ============================================================ zapisane makra

-- macros: definicje makr (JSON) do ponownego użycia. Perspektywy {filtr+kolumny+grupowanie}
-- mieszkają osobno w saved_query (0002); tu tylko potok oblicz/przypisz makra.
CREATE TABLE macros (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    definition_json TEXT NOT NULL,
    created_at      TEXT
);
