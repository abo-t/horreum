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
-- ODWROTNY KIERUNEK ZOSTAJE LEGALNY (marker BEZ rodzaju i powodu) i to jest świadome: wiersz oznaczony
-- przed tą migracją nie ma skąd wziąć rodzaju, a brama przyrostowa (`scan._already_scanned`,
-- `unreadable_since IS NULL`) i tak re-czyta oznaczoną kopię przy najbliższym skanie - wtedy rodzaj
-- się pojawi. Powierzchnia mówi wtedy samą diagnozę albo myślnik, nie zgaduje.
ALTER TABLE location ADD COLUMN unreadable_kind TEXT
    CHECK (unreadable_kind IS NULL OR unreadable_kind IN ('io', 'parse'))
    CHECK (unreadable_kind IS NULL OR unreadable_since IS NOT NULL);
ALTER TABLE location ADD COLUMN unreadable_reason TEXT
    CHECK (unreadable_reason IS NULL OR unreadable_since IS NOT NULL);
