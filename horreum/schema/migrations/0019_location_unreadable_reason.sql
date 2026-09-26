-- 0019 - RODZAJ I POWÓD NIECZYTELNOŚCI KOPII: location.unreadable_kind + location.unreadable_reason (P4-2).
--
-- PRZYROST (ADD COLUMN, jak 0004/0006/0010/0014/0015/0017/0018) - zero zmian istniejących tabel,
-- zero wierszy ruszonych. Kolumny WCHODZĄ PUSTE: wypełnia je KLINGA (`repo.refresh_location_unreadable`,
-- `repo.refresh_location`), nie ta migracja i nie przebieg. Kanon repo (0004:3, `db.py`): migracja
-- nakłada KSZTAŁT, fakty nakłada klinga. Backfillu NIE MA i mieć nie może - populacja oznaczonych kopii
-- jest dziś zerowa, a rodzaju awarii z samego tekstu diagnozy nie da się odtworzyć bez zgadywania
-- (nazwa typu w stringu to nie dowód: astropy potrafi rzucić własny typ przy błędzie I/O).
--
-- CO ZNACZĄ. Marker 0006 (`unreadable_since`) niesie sam CZAS, więc powierzchnia mówiła „kopia
-- nieczytelna" i tym zdaniem OSKARŻAŁA PLIK - także wtedy, gdy plik był zdrowy, a zawiódł dysk albo
-- dostęp. Rodzaj rozdziela dwie sytuacje o dwóch różnych drogach naprawy:
--   * 'io'    - system operacyjny nie oddał bajtów (rodzina `OSError`: brak dostępu, plik znikł między
--               listowaniem a odczytem, timeout SMB, katalog zamiast pliku) - winy szukaj w dysku;
--   * 'parse' - bajty przyszły, a parser nagłówka odmówił - plik jest do zgłoszenia albo naprawy.
-- Trzecia wartość NIE jest faktem o pliku:
--   * 'db'    - błąd bazy danych po NASZEJ stronie: przy zapisie wyniku odczytu (`ingest_record`)
--               albo na bramie przyrostowej (`scan._already_scanned`). Plik mógł być zdrowy, ale
--               marker stoi mimo to, bo wymusza re-odczyt przez bramę - zapis ponawia się sam przy
--               następnym skanie, zamiast utknąć pod pominięciem. Droga naprawy: powtórz skan,
--               a gdy błąd wraca - zgłoś go.
-- `unreadable_reason` to diagnoza „Typ: opis" - ta sama, która idzie do `event.reason` z prefiksem.
--
-- DLACZEGO STAN, A NIE DZIENNIK. Do tej migracji powód mieszkał WYŁĄCZNIE w `event(frame.review)`,
-- a read-model szukał go parą (`sha1:` + `payload.path`) - kopia przemianowana po oznaczeniu gubiła
-- powód, bo payload trzyma ścieżkę z chwili awarii. To ta sama figura, co 0017: read-model liczony
-- ze zdarzeń zamiast ze stanu (pamięć `horreum-review-queue-from-state`).
--
-- ASYMETRIA CZASU (świadoma): `unreadable_since` trzyma PIERWSZĄ awarię (COALESCE), a rodzaj i powód
-- opisują OSTATNIĄ próbę odczytu - marker znaczy „kopia JEST nieczytelna" (bieżący fakt), więc
-- przyczyna ma być bieżąca, nie historyczna.
--
-- STRAŻNIK W DDL, BO BAZA JEST OSTATNIĄ BRAMKĄ (wzorzec 0017). CHECK wiąże oba fakty z markerem:
-- powód bez markera to sprzeczność („kopia jest czytelna, a nie da się jej przeczytać, bo…"). Pisarz,
-- który zgasi marker i zapomni zdjąć rodzaj albo powód, odbija się o `IntegrityError` zamiast zostawić
-- diagnozę przy zdrowej kopii. Sprawdzone sondą przed napisaniem tej migracji - SQLite 3.51 przyjmuje
-- na `ADD COLUMN` dwa CHECK-i na jednej kolumnie, w tym przez kolumnę tego samego wiersza.
--
-- ODWROTNY KIERUNEK ZOSTAJE LEGALNY (marker BEZ rodzaju) i to jest świadome. `NULL` przy markerze
-- znaczy „rodzaj nieznany" w dwóch sytuacjach: wiersz oznaczony przed tą migracją (nie ma skąd wziąć
-- rodzaju) ALBO wyjątek bez kodu systemu, którego nie dało się rozstrzygnąć (goły `OSError` na
-- odczycie, gdy nawet hasz pliku nie przeszedł - `scan.unreadable_kind_of`). Brama przyrostowa
-- (`scan._already_scanned`, `unreadable_since IS NULL`) i tak re-czyta oznaczoną kopię przy
-- najbliższym skanie - wtedy rodzaj może się pojawić. Powierzchnia mówi samą diagnozę albo myślnik,
-- nie zgaduje.
ALTER TABLE location ADD COLUMN unreadable_kind TEXT
    CHECK (unreadable_kind IS NULL OR unreadable_kind IN ('io', 'parse', 'db'))
    CHECK (unreadable_kind IS NULL OR unreadable_since IS NOT NULL);
ALTER TABLE location ADD COLUMN unreadable_reason TEXT
    CHECK (unreadable_reason IS NULL OR unreadable_since IS NOT NULL);
