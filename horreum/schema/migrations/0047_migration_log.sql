-- 0047 - DZIENNIK MIGRACJI TEJ BAZY (AR-318): migration_log(version, applied_at).
--
-- PO CO. `PRAGMA user_version` mówi, DO KTÓREJ wersji baza doszła, ale nie KIEDY. Cofnięcie przerwane
-- nazywa plik „nietkniętym” tylko wtedy, gdy każda wcześniejsza próba jego cofnięcia MUSIAŁABY zostawić
-- ślad - a ślad drogi atomowej zostawia dopiero 0044 (`atomic_undo`). Granicą jest więc chwila, w której
-- TA baza dostała 0044, nie data kodu: baza zmigrowana później pisała commity po dacie kodu, a ich
-- cofnięcia nadal mogły nie zostawić śladu (`writeback._granica_sladu`).
--
-- CO ZNACZY: wiersz = migracja `version` zastosowana w tej bazie o `applied_at` (UTC, zegar SQLite, ta
-- sama transakcja co migracja - `db._apply_migration`). Migracje zastosowane w TYM SAMYM przebiegu przed
-- 0047 dostają wiersz z tą samą chwilą (ten sam moment). Bazy, które dostały 0001..0046 we wcześniejszych
-- przebiegach, wierszy dla nich nie mają - chwili nie da się odtworzyć; czytelnik bierze wtedy chwilę
-- 0047 (ostrożnie: wszystko wcześniejsze „wymaga sprawdzenia”).
--
-- PRZYROST (nowa tabela) - zero ruszonych wierszy. Pisze ją WYŁĄCZNIE infrastruktura migracji
-- (`db.py`, jak `user_version`) - to nie jest zapis domenowy, więc bez `event`.
CREATE TABLE migration_log (
    version    INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL CHECK (length(applied_at) >= 19)
);
