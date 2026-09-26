-- 0020 - UWAGA OBOK WERDYKTU RODOWODU: integration.raw_unreferenced (G2-1d).
--
-- PRZYROST (ADD COLUMN, jak 0017/0018/0019) - zero zmian istniejących kolumn, zero wierszy ruszonych.
-- Kolumna WCHODZI PUSTA: wypełnia ją przebieg rodowodu przez klingę (`repo.upsert_integration`),
-- nie ta migracja. Backfillu nie ma i mieć nie może - liczba należy do PRZEBIEGU (okno, zegar,
-- materiał w chwili liczenia), a najbliższy „Policz rodowód stosów" i tak ją ustawi.
--
-- CO ZNACZY. Ile klatek RAW przebieg widział w pasie okna mastera (ten sam obiekt, filtr, próg
-- ekspozycji) i NIE umiał umieścić w czasie, bo odniesienia zegara tego obrazu nikt nie wskazał
-- (`stacks._in_window`, trzecia wartość zwrotu). Do tej migracji liczba miała czytelnika TYLKO
-- wtedy, gdy stawała się werdyktem `offset_unknown`; przy puli MIESZANEJ (okno domknięte z FITS-ów,
-- obok RAW-y bez zegara) stos dostawał rodowód, a RAW-y milkły bez śladu.
--
-- DLACZEGO KOLUMNA OBOK WERDYKTU, A NIE LISTA W JEDNEJ KOLUMNIE. Werdykt (`unresolved_reason`)
-- zostaje JEDNOWARTOŚCIOWY - czytają go perspektywa Zbiorów, kubełek Porządków, predykat zwietrzenia
-- i bramka §5.14, więc zamiana go w listę ruszyłaby każdego z nich. Uwaga idzie OBOK, jako osobny
-- fakt z własnym strażnikiem w DDL: baza jest ostatnią bramką słownika (kanon 0012/0019), a lista
-- tokenów w JSON-ie wyprowadziłaby słownik z bazy do kodu (CHECK nie zagląda do `json_each`).
-- „Lista uwag" to więc werdykt + niepuste kolumny uwag; kolejna uwaga = kolejne ADD COLUMN.
--
-- STRAŻNIKI W DDL:
--   * `> 0` - zero znaczy „brak uwagi", a brak uwagi ma JEDNĄ postać (NULL). Dwie postaci tego
--     samego stanu rozjechałyby porównanie kompletu faktów w klindze (przebieg pisałby `0` na `NULL`
--     i emitował `integration.updated` bez zmiany treści);
--   * nie przy werdykcie `offset_unknown` - ten werdykt MÓWI dokładnie to samo („kandydaci są, tylko
--     liczą w innym zegarze"), więc uwaga obok byłaby dublem, a panel powiedziałby to dwa razy.
-- Sprawdzone jak przy 0019: SQLite przyjmuje na ADD COLUMN dwa CHECK-i, w tym przez kolumnę tego
-- samego wiersza.
ALTER TABLE integration ADD COLUMN raw_unreferenced INTEGER
    CHECK (raw_unreferenced IS NULL OR raw_unreferenced > 0)
    CHECK (raw_unreferenced IS NULL OR unresolved_reason IS NULL
           OR unresolved_reason <> 'offset_unknown');
