-- 0030 - BACKUP NIEPOTWIERDZONY (AR-40): `header_backups.pending_since`.
--
-- PRZYROST (jedna kolumna `ADD COLUMN`) - zero przebudowy tabeli, zero kasowania wierszy.
--
-- Backup drogi atomowej powstaje PRZED podmianą pliku (Z3, 2026-09-26). Proces, który zginie między
-- utrwaleniem backupu a podmianą (albo podmiana, która rzuci, choć mogła zajść), zostawiał wiersz
-- nierozróżnialny od backupu commitu wykonanego: ponowiony zapis tej samej zmiany dawał ten sam
-- `post_hash`, a cofnięcie STAREGO commitu przechodziło kontrolę i cofało nagłówek należący do
-- późniejszego.
--
-- `pending_since` = chwila utrwalenia backupu drogi atomowej, który czeka na potwierdzenie podmiany.
-- Gaśnie (NULL) w transakcji straży podmiany zaraz po udanej podmianie (`repo.confirm_backup_replaced`),
-- przy odmowie straży (`repo.mark_backup_unreplaced`, razem z `unreplaced_at`) albo w rekoncyliacji
-- z dyskiem (`repo.settle_pending_backup`), którą pisarz robi, zanim tknie lokację (commit, cofnięcie).
-- NULL = backup potwierdzony, odbity albo sprzed 0030 (zachowanie jak dotąd), oraz backup drogi
-- w miejscu - jego stan niesie dziennik `inplace_op`.
--
-- BACKFILLU NIE MA: wiersze sprzed migracji nie mają śladu, czy podmiana zaszła; zostają przy
-- znaczeniu sprzed 0030 (kandydat cofnięcia, kotwica `post_hash` odbija plik nietknięty).
ALTER TABLE header_backups ADD COLUMN pending_since TEXT;

-- `pending_rows` = JSON wpisów stagingu, które zapisuje TA próba (droga atomowa): `id` RAZEM z treścią
-- operacji (keyword, idx, op, wartość, typ, komentarz) - samo `id` nie wystarcza, bo ponowny staging po
-- skasowaniu starego dostaje te same `rowid`. Rekoncyliacja, która potwierdzi podmianę z dysku, oznacza
-- 'applied' wyłącznie wpisy zgodne z tym zapisem - wpis dodany ponownym stagingiem pod tym samym `run_id`
-- z inną treścią do pliku nie trafił i nie może zniknąć jako wykonany (bramka astra, A5). Rekoncyliacja
-- z nagłówkiem ani sprzed, ani po commicie stawia `unreplaced_at`: backup bez dowodu wykonania nie cofa (A3).
ALTER TABLE header_backups ADD COLUMN pending_rows TEXT;

-- Bramka commitu i cofnięcia pyta o backupy niepotwierdzone lokacji przy KAŻDYM pliku; zbiór jest
-- pusty w zwykłym biegu, więc indeks częściowy zostaje mały, a pytanie nie skanuje tabeli.
CREATE INDEX idx_header_backups_pending ON header_backups (location_id)
    WHERE pending_since IS NOT NULL;
