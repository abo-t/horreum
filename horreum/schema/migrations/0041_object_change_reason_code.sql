-- 0041 - KOD POWODU POZYCJI ZMIANY OBIEKTU (AR-141): powód pozycji przebiegu „Zmień obiekt…”/„Uzgodnij”
-- leżał w `pending_object_change.reason` wyłącznie jako polska proza, a okno otwierane z Porządków
-- czyta go z bazy - UI po angielsku pokazywało go po polsku. Obok prozy wchodzi KOD powodu i jego
-- PARAMETRY; okno składa z nich zdanie w języku UI (`objchg.item.<kod>`), proza zostaje dla CLI, logu
-- i wierszy bez kodu.
--
-- PRZYROST (ADD COLUMN) - zero przebudowy, zero ruszonych wierszy, BEZ backfillu: na żywym archiwum
-- powód ma 1 z 427 pozycji (sonda 2026-10-14 na kopii `Connection.backup`) - surowy błąd przeniesienia
-- sprzed AR-125, który okno i tak mówi w języku UI (`czytelny_powod`). Zgadywanie kodu z prozy byłoby
-- drugim parserem dawnych zdań. Wiersz z kodem NULL = proza jak dotąd.
--
-- TRÓJKĘ `reason`/`reason_code`/`reason_args` pisze WYŁĄCZNIE `repo._set_object_change_reason_tx`
-- (kodek `item_reasons.do_bazy`); `reason_args` to obiekt JSON parametrów (powód niższej warstwy
-- zagnieżdżony jako `{text, code, args}`, uwagi jako lista `notes`).
--
-- STRAŻNIK W DDL (baza jest ostatnią bramką, wzorzec 0040): kod nigdy bez prozy (CLI i log czytają
-- prozę), parametry wyłącznie razem z kodem i zawsze jako obiekt JSON.
ALTER TABLE pending_object_change ADD COLUMN reason_code TEXT
    CHECK (reason_code IS NULL OR (length(reason_code) > 0 AND reason IS NOT NULL));
ALTER TABLE pending_object_change ADD COLUMN reason_args TEXT
    CHECK ((reason_args IS NULL) = (reason_code IS NULL)
           AND (reason_args IS NULL
                OR (json_valid(reason_args) AND json_type(reason_args) = 'object')));
