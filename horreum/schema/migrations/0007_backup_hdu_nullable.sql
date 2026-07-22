-- Horreum — migracja 0007: `header_backups.hdu_index` staje się NULLABLE (P6/D-X-14).
-- Źródło prawdy: brief/PLAN_p6_xisf_writeback.md D-X-7 + D-X-14.
--
-- DLACZEGO: `hdu_index` to fakt FITS-owy (numer HDU naukowego). XISF nie zna pojęcia HDU, więc
-- `location.hdu_index` dla pliku XISF jest NULL (D-X-7) — a `header_backups.hdu_index` był
-- `NOT NULL` (0003_writeback.sql:52). Pisarz XISF (P6c) wstawiałby tam NULL i dostawał
-- IntegrityError PO udanym `os.replace`: plik już zmieniony, backupu brak, undo niemożliwe.
-- Sentinel `0` odrzucony świadomie — czytałby się jako „HDU numer 0", czyli KŁAMSTWO, i dawał
-- dwie różne odpowiedzi na to samo pytanie (`location.hdu_index` NULL vs backup 0). Wartość jest
-- wyłącznie dokumentacyjna (`writeback.undo_commit` jej nie używa), więc NULL = „nie dotyczy".
--
-- SQLite nie umie zdjąć NOT NULL przez ALTER — stąd PRZEBUDOWA TABELI (create/copy/drop/rename).
-- Bezpieczna, bo `header_backups` nie jest celem żadnego FK ani triggera; jej WŁASNE FK
-- (commits, location) odtwarzamy 1:1. Dane kopiowane w całości (tabela append-only — historia undo
-- NIE może zniknąć przy migracji), na żywej bazie zwykle 0–kilkaset wierszy.
-- Reszta DDL identyczna z 0003: `header_text` z CHECK-iem długości, `post_hash` NOT NULL,
-- UNIQUE(commit_id, location_id), indeks po commit_id (odtwarzany po RENAME, bo nazwa indeksu
-- jest globalna i stary zniknął razem ze starą tabelą).

CREATE TABLE header_backups_new (
    id          INTEGER PRIMARY KEY,
    commit_id   INTEGER NOT NULL REFERENCES commits (id),
    location_id INTEGER NOT NULL REFERENCES location(id),
    hdu_index   INTEGER,                     -- NULL = „nie dotyczy" (XISF nie ma HDU, D-X-7)
    header_text TEXT NOT NULL CHECK (length(header_text) > 0),
    post_hash   TEXT NOT NULL,
    UNIQUE (commit_id, location_id)
);

INSERT INTO header_backups_new (id, commit_id, location_id, hdu_index, header_text, post_hash)
    SELECT id, commit_id, location_id, hdu_index, header_text, post_hash FROM header_backups;

DROP TABLE header_backups;
ALTER TABLE header_backups_new RENAME TO header_backups;
CREATE INDEX idx_header_backups_commit ON header_backups (commit_id);
