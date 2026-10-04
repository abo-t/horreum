-- 0027 - PROWENIENCJA osi obserwatorium: frame.observatory_source (stanowisko wskazane RĘKĄ).
--
-- PRZYROST (ADD COLUMN, jak 0015) - zero zmian istniejących tabel, zero wierszy ruszonych. Kolumna
-- WCHODZI PUSTA i taka zostaje dla całego archiwum: wypełnia ją GEST CZŁOWIEKA („Wskaż stanowisko…"
-- w widoku stanowisk, `horreum observatory assign`), nie ta migracja i nie przebieg. Kanon repo
-- (0004:3, 0015): migracja nakłada KSZTAŁT, fakty nakłada KLINGA.
--
-- CO ZNACZY: `frame.observatory_source = 'user'` - stanowisko wskazała RĘKA, bo plik nie miał czym
-- zeznać albo zeznał źle. Wzorcowa populacja: RAW-y z lustrzanki bez modułu GPS (LMC - 36 DNG,
-- a za nimi wyjazdy na półkulę południową). DNG jest read-only, więc writeback `SITELAT`/`SITELONG`
-- nie wejdzie tu NIGDY - jedyną drogą jest baza (ta sama luka strukturalna co przy 0015).
--
-- NULL = oś wyliczył AUTOMAT z nagłówka (`resolver.resolve_observatory`) albo osi jeszcze nie ma.
-- Automat własnego źródła nie zapisuje - powód jak w 0015 (`assign_observatory` jest idempotentny
-- po `observatory_id`, więc zapis „wyliczone" złapałby wyłącznie klatki akurat ZMIENIAJĄCE stanowisko).
--
-- CO Z TEGO WYNIKA DLA PRZEBIEGU: źródło z tej kolumny jest LEPKIE. `resolve_observatory` mija
-- klatkę ze stanowiskiem od ręki BEZ zapisu - także wtedy, gdy klatka MA GPS (nagłówek nie
-- przegłosowuje ręki; rozjazd liczy się w podsumowaniu przebiegu, nie przepina osi).
--
-- Strażnik w DDL (wzorzec 0015 i 0017): słownik wartości ORAZ wiązanie źródła z osią - „ręka
-- wskazała stanowisko", którego nie ma, to zdanie bez podmiotu (lekcja `reka_bez_osi` z 0015,
-- tu domknięta w DDL od pierwszego dnia, bo kolumna nie ma jeszcze ani jednego wiersza).
-- Lustro w kodzie: `repo.OBSERVATORY_SOURCES` (test pinuje równość obu list).
ALTER TABLE frame ADD COLUMN observatory_source TEXT
    CHECK (observatory_source IS NULL
           OR (observatory_source IN ('user') AND observatory_id IS NOT NULL));
