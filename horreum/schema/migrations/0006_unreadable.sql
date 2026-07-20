-- Horreum — migracja 0006: znacznik czytelności KOPII w STANIE (#13).
-- Źródło prawdy: issue #13 „Kopia, która stała się nieczytelna, nie zostawia śladu w stanie".
-- PRZYROST nad 0005 (ADD kolumny, zero zmian istniejących). DLACZEGO: przed #13 nieczytelna kopia
-- zostawiała TYLKO event(frame.review) — kolejka przeglądu (ze STANU po #12) go nie widziała, a po
-- odświeżeniu mtime brama przyrostowa już nigdy nie czytała pliku ponownie (alarm milkł po jednym
-- przebiegu). Marker w STANIE zamyka obie dziury: kolejka pokazuje „kopia nieczytelna" jak „bez
-- nagłówka", a brama re-czyta oznaczoną kopię do skutku (patrz scan._already_scanned).

-- unreadable_since: NULL => kopia czytelna; ISO-8601 = timestamp PIERWSZEJ nieudanej próby odczytu
-- (COALESCE trzyma pierwszy — idempotencja przy powtórnej awarii bez zmiany mtime). Gaśnie DOPIERO
-- po udanym odczycie (repo.refresh_location wpuszcza go do diffu faktów kopii, więc samo przejście
-- markera jest zmianą). Fakt KOPII (na location, nie na frame — jak file_sha1/size_bytes, R2#6).
ALTER TABLE location ADD COLUMN unreadable_since TEXT;
