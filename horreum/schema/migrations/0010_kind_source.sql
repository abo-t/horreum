-- 0010 — PROWENIENCJA rodzaju klatki: frame.kind_source (#2, DSLR/RAW, D-R-4).
--
-- PRZYROST (ADD COLUMN, jak 0004/0006) — zero zmian istniejących tabel, re-skan/nowy ingest
-- wypełnia. Wzorzec kolumny = `frame.object_source` (0002:20): źródło osi jawne, nie domyślane.
--
-- Wartości: 'header' (kind z IMAGETYP zeznania FITS/XISF) | 'path' (kind z FOLDERU — RAW nie ma
-- IMAGETYP w EXIF, ścieżka jako źródło faktu, precedens C1) | NULL (nieczytelny W1 albo wiersz
-- sprzed tej migracji — prowieniencja nieznana, uczciwie).
ALTER TABLE frame ADD COLUMN kind_source TEXT;   -- header|path|NULL
