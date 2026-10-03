-- 0026 - WERSJE STOSÓW (AR-10): werdykt „zostawiam wszystkie" grupy bliźniaków + chwila utworzenia
-- pliku stosu (`XISF:CreationTime`).
--
-- PRZYROST (jedna tabela + jedna kolumna `ADD COLUMN`) - zero przebudowy, zero ruszonych wierszy.
--
-- 1. `stack_version_kept` - WERDYKT CZŁOWIEKA o grupie wersji: „zostawiam wszystkie, nie wracam do
--    tego". Do tej migracji jedyną drogą do zera wiersza Porządków „Wersje stosów" było skasowanie
--    pliku poza programem, więc wiersz stał poza plakietką (świeciłby wiecznie po prawowitej decyzji
--    „zostawiam obie"). Z werdyktem wiersz liczy się do plakietki tylko grupami BEZ werdyktu.
--
--    WIERSZ NA CZŁONKA, NIE NA GRUPĘ: grupa jest POCHODNĄ (`queries._grupy_wersji` - klucz z obiektu,
--    kamery, teleskopu kanonicznego, filtra, ekspozycji i okna), nie ma własnej tożsamości w bazie.
--    Werdykt przypięty do napisu klucza ginąłby przy każdym scaleniu teleskopu albo przepięciu
--    obiektu, choć zbiór stosów się nie zmienił. Przypięty do klatek opisuje dokładnie to, co człowiek
--    widział: TE stosy zostają. `group_key` = identyfikator grupy z chwili werdyktu (wspólny dla
--    wszystkich członków jednego gestu) - po nim read-model rozpoznaje, że werdykt objął CAŁĄ grupę:
--    grupa ma werdykt, gdy KAŻDY jej obecny członek ma wiersz i wszystkie wiersze niosą ten sam klucz.
--    Nowa wersja (nowy stos w grupie) nie ma wiersza → grupa wraca do roboty; dwie grupy z osobnymi
--    werdyktami zlane w jedną (np. po przepięciu obiektu) mają dwa klucze → też wraca. Klucz NIE jest
--    porównywany z bieżącym identyfikatorem grupy, z powodu wyżej (scalenie teleskopu).
--    FK do `frame`: werdykt bez klatki nie ma sensu, a kasacji klatek Horreum nie robi.
--    Pisze WYŁĄCZNIE klinga `repo.keep_stack_versions` / `repo.reopen_stack_versions` (z eventem).
--
-- 2. `integration.creation_time` - `XISF:CreationTime` z nagłówka pliku stosu: chwila, w której
--    PixInsight zapisał plik. Data integracji z sygnatury (`PCL:Signature:Integration`) istnieje
--    dopiero od modułu XISF 1.1.2 (marzec 2025) - stosy starsze nie mają jej wcale, a `CreationTime`
--    zapisuje już moduł 1.0.13 (zmierzone na lokalnych kopiach stosów 2026-10-03; przy obu formatach
--    `CreationTime` stoi ~2 min po sygnaturze, czyli to zapis zaraz po integracji). Własności XISF
--    skan świadomie nie wciąga do `cards`, więc fakt jest w pliku, nie w bazie.
--    Wchodzi PUSTA. Wypełnia ją przebieg rodowodu stosów (`stacks.run_stack_lineage` → klinga
--    `repo.upsert_integration`), który czyta nagłówek XML KAŻDEGO stosu przy każdym przebiegu - więc
--    najbliższe „Stosy" w Dostawie uzupełnią całe archiwum bez osobnej fazy. SQL tego faktu nie zna,
--    więc backfillu nie ma.
--    Format jak w pliku (ISO z `Z`), bez interpretacji - lustro `integration.tool`.
CREATE TABLE stack_version_kept (
    frame_id   INTEGER PRIMARY KEY REFERENCES frame (id),
    group_key  TEXT NOT NULL CHECK (group_key <> ''),
    decided_at TEXT NOT NULL
);

ALTER TABLE integration ADD COLUMN creation_time TEXT;
