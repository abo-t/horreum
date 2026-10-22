-- 0046 - ZBADANIE BAJTU SPOZA DRUKOWALNEGO ASCII W SUROWYM NAGŁÓWKU KOPII FITS (AR-299):
-- location.nonprintable_hash + nonprintable_keyword + nonprintable_char.
--
-- PO CO. Pisarz FITS odmawia zapisu i cofnięcia pliku, którego surowy nagłówek ma bajt spoza 0x20-0x7E
-- (`header_nonprintable`, AR-271): astropy czyta bajt >= 0x80 jako `?`, a `writeto` tak by go zapisał.
-- Do tej migracji plik czekał niewidoczny do pierwszej próby zapisu. Skan zeznaje bajt tym samym
-- predykatem co pisarz (`card_rules.bajt_spoza_ascii`), a kubełek Porządków liczy ze STANU tej kopii.
--
-- CO ZNACZĄ:
--   * `nonprintable_hash` - odcisk nagłówka (`location.header_hash`), przy którym surowe bajty ZBADANO.
--     NULL albo odcisk inny niż bieżący = NIE ZBADANO - i to nie jest „czysto”. Kotwica odcisku, nie
--     sama flaga: odcisk skanu nie odróżnia bajtu 0xE9 od dosłownego `?` (oba to `?` po astropy), więc
--     o zbadaniu mówi wyłącznie odczyt surowych bajtów przy TYM nagłówku; zmiana nagłówka bez
--     zbadania (import z dawcy) sama unieważnia stary stan.
--   * `nonprintable_keyword`/`nonprintable_char` - pierwsza karta z takim bajtem i bajt `0xNN` (jak
--     parametry zdania pisarza); NULL przy zbadanym = czysto.
--
-- PRZYROST (ADD COLUMN, jak 0019/0021) - zero zmian istniejących tabel, zero wierszy ruszonych.
-- Kolumny WCHODZĄ PUSTE (wszystkie kopie niezbadane): wypełnia je KLINGA - skan przy każdym odczycie
-- (`repo.add_location`/`refresh_location`), etap uzupełnień Dostawy dla kopii sprzed migracji
-- (`scan.backfill_copy_facts` → `repo.record_nonprintable`) i pisarz przy odmowie z tym kodem
-- (`repo.block_on_nonprintable`). Migracja nakłada kształt i udziału nie czyta. Populacja zmierzona
-- 2026-10-21 surowym odczytem: 0 z 15 598 plików FITS na `R:` - ale baza tego nie wie, dopóki etap
-- uzupełnień nie przejdzie (do tego czasu Porządki mówią „niesprawdzone”, nie zero).
--
-- STRAŻNIK W DDL (wzorzec 0019): nazwa karty tylko przy zbadaniu, bajt zawsze razem z nazwą
-- i w postaci `0xNN`. Indeks częściowy pod kubełek (kopie z bajtem) - zmierzone na kopii pf4: 0,01-0,15 ms
-- zamiast 18 ms pełnego przebiegu `location`.
ALTER TABLE location ADD COLUMN nonprintable_hash TEXT;
ALTER TABLE location ADD COLUMN nonprintable_keyword TEXT
    CHECK (nonprintable_keyword IS NULL OR nonprintable_hash IS NOT NULL);
ALTER TABLE location ADD COLUMN nonprintable_char TEXT
    CHECK ((nonprintable_char IS NULL) = (nonprintable_keyword IS NULL)
           AND (nonprintable_char IS NULL OR nonprintable_char GLOB '0x[0-9A-F][0-9A-F]'));
CREATE INDEX idx_location_nonprintable ON location(frame_id) WHERE nonprintable_keyword IS NOT NULL;
