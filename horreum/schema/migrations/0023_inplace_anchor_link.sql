-- 0023 - KOTWICA OPERACJI I WIĄZANIE ZE STAGINGIEM dla zapisu w miejscu (astra, 2026-09-27).
--
-- PRZYROST (dwie kolumny `ADD COLUMN` + indeks) - zero przebudowy tabel, zero kasowania wierszy.
-- Obie kolumny pisze WYŁĄCZNIE klinga (`repo.begin_inplace_commit` / `repo.begin_inplace_undo`),
-- wołana przez pisarza `writeback` pod blokadą pliku, w TEJ SAMEJ transakcji co operacja.
--
-- `inplace_op.anchor_sha1` = sha1 CAŁEGO pliku sprzed zapisu, ustalony przez pisarza przed pierwszym
--   bajtem (kotwica bazy potwierdzona regułą `mtime` albo pełnym odczytem uchwytu blokady). Kontrola
--   danych dokończenia i odzysku porównuje z NIĄ plik z podstawionym starym regionem operacji.
--   Dawniej kotwicą była `location.file_sha1` - kolumna MUTOWALNA: spóźniony zapis faktów (odczyt
--   uzupełnienia sprzed operacji albo z pliku już uszkodzonego) przestawiał ją, a dokończenie brało
--   „sha1 pliku == kotwica" za dowód wcześniejszej synchronizacji i przepuszczało plik z bajtem
--   zmienionym poza nagłówkiem. Kotwica przy operacji jest niezmienna od chwili jej utrwalenia.
--   NULL = operacja sprzed 0023 (pisarz kotwicy nie utrwalał) - `writeback._kotwica_operacji`
--   wyprowadza ją wtedy z koperty backupu albo z bazy, o ile baza wciąż opisuje plik sprzed operacji.
--
-- `pending_changes.inplace_op_id` = operacja, która zapisała ten wpis stagingu. Dokończenie
--   (`repo.finish_inplace_op`) i powrót (`repo.revert_inplace_op`) zmieniają status DOKŁADNIE tych
--   wierszy, w tej samej transakcji co faza operacji. Dawniej dokończenie szukało wierszy po
--   statusie 'failed' w przebiegu commitu, więc crash po utrwaleniu `written`, a przed oznaczeniem
--   stagingu, zostawiał wiersze 'pending' na zawsze (nagrobek ręki nie gasł, ponowny commit
--   odbijał się od `header_hash mismatch`).
--
-- BACKFILL WIĄZANIA wyłącznie tam, gdzie jest czego dokończyć: operacja commitu w fazie `written`
-- i wiersze TEGO przebiegu i TEJ lokacji w statusie 'pending' (crash przed oznaczeniem) albo 'failed'
-- (re-sync padł - tak oznaczała je droga sprzed 0023). Jedna lokacja idzie w jednym przebiegu jedną
-- grupą wierszy, więc para (przebieg, lokacja) wskazuje wiersze zapisane przez tę operację. Inne fazy
-- nie czekają na dokończenie - ich wiersze zostają bez wiązania. Kotwicy (`anchor_sha1`) migracja NIE
-- wylicza: SQL nie zna bajtów pliku.
ALTER TABLE inplace_op ADD COLUMN anchor_sha1 TEXT;
ALTER TABLE pending_changes ADD COLUMN inplace_op_id INTEGER REFERENCES inplace_op(id);
CREATE INDEX idx_pending_inplace_op ON pending_changes (inplace_op_id);
UPDATE pending_changes SET inplace_op_id = (
        SELECT MAX(o.id) FROM inplace_op o JOIN commits c ON c.id = o.commit_id
        WHERE o.kind = 'commit' AND o.phase = 'written'
          AND c.run_id = pending_changes.run_id AND o.location_id = pending_changes.location_id)
    WHERE status IN ('pending', 'failed') AND inplace_op_id IS NULL
      AND EXISTS (
        SELECT 1 FROM inplace_op o JOIN commits c ON c.id = o.commit_id
        WHERE o.kind = 'commit' AND o.phase = 'written'
          AND c.run_id = pending_changes.run_id AND o.location_id = pending_changes.location_id);
