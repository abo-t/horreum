-- 0028 - KANAŁ gotowego obrazu (P4-3): `frame.channel` - który kanał kamery kolorowej niesie stos.
--
-- PRZYROST (jedna kolumna `ADD COLUMN`) - zero przebudowy, zero ruszonych wierszy.
--
-- Kamera kolorowa daje z jednej sesji trzy stosy kanałów (WBPP integruje R, G i B osobno), a baza
-- tego nie wiedziała: `filter_canon` niesie filtr OPTYCZNY (L-Pro, L-eXtreme) albo NULL, więc trzy
-- kanały jednej integracji wyglądały w bazie jak trzy kopie tego samego obrazu. Fakt żyje WYŁĄCZNIE
-- w nazwie pliku (`…_FILTER-LPRO__B.xisf`, `…_NoFilter_60s_B.xisf`).
--
-- POCHODNA, nie zeznanie: wartość liczy z `location.path` resolver (`resolver.derive_channels`,
-- reguła nazwy `resolve.channel`) i zapisuje klingą `repo.backfill_frame_channel` z JEDNYM eventem
-- na przebieg (kanon `filter.backfilled`). Klatka bez kanału w nazwie (mono, obraz pełnokolorowy,
-- light) ma NULL - to stan poprawny, nie luka. Kolumna wchodzi PUSTA: SQL nie zna reguły nazwy,
-- a najbliższy przebieg resolvera (każda Dostawa i droga „Stosy") wypełni archiwum bez odczytu
-- plików.
--
-- Strażnik w DDL: słownik wartości. Lustro w kodzie: `resolve.channel.CHANNELS` (test pinuje
-- równość obu list).
ALTER TABLE frame ADD COLUMN channel TEXT
    CHECK (channel IS NULL OR channel IN ('R', 'G', 'B'));
