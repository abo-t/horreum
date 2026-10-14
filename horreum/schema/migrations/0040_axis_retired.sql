-- 0040 - NAGROBEK OBIEKTU I TELESKOPU (AR-133, AR-137, decyzja `Q8`): „Cofnij” gestu, który założył
-- obiekt albo teleskop, zdejmuje go z list wyboru, gdy nie ma on klatek ani faktów ręki spoza gestu.
--
-- PRZYROST (ADD COLUMN + jedna nowa tabela) - zero przebudowy, zero ruszonych wierszy, BEZ backfillu:
-- na żywym archiwum obiektów i teleskopów z 0 klatek jest 0/0 (sonda 2026-10-14, `?mode=ro`), więc
-- kontrakt przypinają testy. Kanon repo (0004:3, 0017): migracja nakłada KSZTAŁT, fakty nakłada klinga.
--
-- NAGROBEK = KOLUMNA, NIE `DELETE` (zapowiedź `audit.entity_event_parity`): wiersz, dziennik i pola
-- ręki zostają, `retired_at` = chwila zdjęcia, NULL = żywy. Pisze go wyłącznie klinga
-- `repo.retire_orphan` (zdarzenie `object.retired`/`telescope.retired`), a zdejmuje założenie pod
-- tą samą nazwą (`*.unretired`: gest ręki, przebieg resolvera albo groupera, „Dopisz nowy…"). Pól
-- ręki teleskopu (`label`, `focal_user`, `f_ratio_user`, `in_park`, `status`) nagrobek NIE zeruje -
-- inaczej spis ręki (`horreum human-facts --baseline`) zgłosiłby ubytek, którego nie było.
--
-- STRAŻNIK W DDL (baza jest ostatnią bramką, wzorzec 0017): teleskop scalony nie bywa nagrobkiem -
-- scalenie mówi „to ten sam sprzęt co inny”, nagrobek - „takiego teleskopu nie ma”. SQLite przyjmuje
-- na `ADD COLUMN` CHECK przez kolumny tego samego wiersza (sprawdzone przy 0017).
ALTER TABLE object ADD COLUMN retired_at TEXT
    CHECK (retired_at IS NULL OR length(retired_at) > 0);
ALTER TABLE telescope ADD COLUMN retired_at TEXT
    CHECK (retired_at IS NULL OR (length(retired_at) > 0 AND merged_into IS NULL));

-- ŚLAD „ZMIEŃ OBIEKT…” (0036): obiekt założony albo wskrzeszony przez TEN przebieg i alias wpisanej
-- nazwy założony przez TEN przebieg - oba zapisywane w tej samej transakcji co `INSERT` albo
-- wskrzeszenie (`repo.apply_object_change_item`). Własności aliasu NIE wyprowadzamy z `source` ani
-- z wieku wiersza: alias `user` bywa ręką sprzed gestu, a kontrakt ochrony ręki zabrania kasować go
-- mechanizmowi bez własności (`repo.retire_alias_and_unassign`). Identyfikator aliasu jest BEZ FK:
-- nagrobek obiektu kasuje alias (`object.alias_retired`), a ślad przebiegu zostaje historią. Kotwicą
-- pary jest też `alias_norm` przebiegu - id wiersza SQLite bywa użyte ponownie po skasowaniu
-- najwyższego.
ALTER TABLE object_change_run ADD COLUMN made_object_id INTEGER REFERENCES object (id);
ALTER TABLE object_change_run ADD COLUMN made_alias_id INTEGER;

-- ŚLAD „DOPISZ NOWY…” (`repo.user_assign_config_new_telescope`): teleskop i granice zdarzeń gestu.
-- Gest to jedna transakcja `BEGIN IMMEDIATE`, więc jego zdarzenia leżą w dzienniku ciągiem od
-- `first_event_id` do `last_event_id` (dziennik jest append-only, id nie wracają). Cofnięcie
-- (`repo.undo_new_telescope`) odtwarza stan klatek sprzed gestu z par `config.unassigned`/
-- `config.assigned` w tych granicach (klatka bez `config.unassigned` miała `config_id` NULL),
-- a zdarzenia ręki na teleskopie PO `last_event_id` są powodem odmowy nagrobka - zdarzenia samego
-- gestu (`proposed`, `labeled`, `approved`, optyka, `parked`, `config.*`) nim nie są. `undone_at` =
-- cofnięcie wykonane (drugie nie ma czego cofać). Wiersze to księgowość gestu (jak `run_dir`), bez
-- własnych zdarzeń.
CREATE TABLE telescope_add (
    id             INTEGER PRIMARY KEY,
    telescope_id   INTEGER NOT NULL REFERENCES telescope (id),
    first_event_id INTEGER NOT NULL,
    last_event_id  INTEGER NOT NULL,
    created_at     TEXT    NOT NULL CHECK (length(created_at) > 0),
    undone_at      TEXT,
    CHECK (last_event_id >= first_event_id)
);
CREATE INDEX idx_telescope_add_tel ON telescope_add (telescope_id);
