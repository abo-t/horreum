-- 0025 - WERSJA REGUŁY KOERCJI FAKTÓW KOPII (AR-33): `location.hdr_rule`.
--
-- PRZYROST (jedna kolumna `ADD COLUMN`) + jednorazowe stemplowanie wierszy z zebranymi faktami.
--
-- Fakty kopii `hdr_*` (0021) są wartościami PO koercji (`resolve.headers.copy_testimony` przez
-- `_to_text`/`_to_float`/`_to_int`), a kotwica `hdr_hash` mówi tylko, Z JAKIEGO nagłówka powstały -
-- nie, JAKĄ regułą. Zmiana koercji (np. `_to_text` zacznie zdejmować białe znaki) zostawiłaby kopie
-- zebrane starą regułą obok kopii zebranych nową, a porównanie kopii jednej klatki widziałoby rozjazd
-- samego rzutu („Klatki z niezgodnymi kopiami" bez różnicy w plikach). Sterownik uzupełnienia brał
-- dotąd wyłącznie `hdr_hash IS NULL`, więc stare fakty nie miały drogi do odświeżenia.
--
-- `hdr_rule` = numer reguły, którą zebrano fakty tego wiersza (stała `COPY_TESTIMONY_RULE` przy
-- koercji w `resolve/headers.py`); stempluje go każdy zapis faktów kopii (`repo.add_location`,
-- `repo.refresh_location`, `repo.record_copy_facts`). NULL = faktów nie ma ALBO reguła nieznana -
-- oba przypadki dobiera sterownik (`scan.copy_facts_candidates`: `hdr_hash IS NULL OR hdr_rule IS
-- NULL OR hdr_rule < bieżąca`), a porównanie kopii (`queries.copy_divergence`) traktuje kopię spoza
-- bieżącej reguły jak kopię bez faktów: „nie wiem", nie „inaczej".
--
-- BACKFILL = 1 dla wierszy z faktami, NULL dla reszty. Reguła 1 to jedyna reguła, jaką fakty kopii
-- kiedykolwiek zebrano: `resolve/headers.py` i `resolve/_coerce.py` nie zmieniły się od commitu,
-- który wprowadził 0021 (`git log d2db352..` po obu plikach pusty, sprawdzone 2026-10-03). Stempel 1
-- jest więc odczytem prawdy, nie domysłem - a NULL wysłałby wszystkie ~548 zebranych kopii do
-- ponownego czytania nagłówka po SMB, choć żadna wartość by się nie zmieniła.
--
-- CHECK: reguła jest liczbą całkowitą >= 1 i stoi wyłącznie przy kotwicy (reguła bez faktów to
-- sprzeczność, wzorzec 0019/0021). Kotwica BEZ reguły zostaje legalna - to stan „reguła nieznana",
-- który sterownik dobiera; zakaz dawałby IntegrityError przy samym `ADD COLUMN` (SQLite testuje
-- CHECK na istniejących wierszach, zanim UPDATE niżej zdąży je ostemplować).
ALTER TABLE location ADD COLUMN hdr_rule INTEGER
    CHECK (hdr_rule IS NULL
           OR (typeof(hdr_rule) = 'integer' AND hdr_rule >= 1 AND hdr_hash IS NOT NULL));
UPDATE location SET hdr_rule = 1 WHERE hdr_hash IS NOT NULL;
