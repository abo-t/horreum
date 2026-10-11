-- 0035 - WARIANT KADRU STOSU (AR-54): autocrop jako osobna klatka powiązana z oryginałem.
--
-- PRZYROST (dwie nowe tabele) - zero przebudowy, zero ruszonych wierszy. Tabele wchodzą PUSTE:
-- relację zapisuje konsument zeznania wariantu po skanie (`stack_variants.link_from_testimonies`,
-- woła go `grouper.run_grouper` przed osią sprzętu), gdy oba pliki pary leżą już w bazie.
--
-- DLACZEGO OSOBNA KLATKA, A NIE KOPIA: autocrop ma INNE dane (przycięty kadr), więc inną tożsamość
-- `sha1_data`. Przycięcie robi PixInsight po integracji, a WBPP często zdejmuje przy tym karty
-- `TELESCOP`/`OBJECT` - wariant bez relacji nie ma zestawu ani obiektu (AR-54). Relacja niesie
-- dziedziczenie (obiekt ze źródłem `twin`, zestaw w przebiegu sprzętu) i odsiewa parę z grup
-- „wersji stosów” (0026, `gui.queries._grupy_wersji`): wariant kadru nie jest drugą integracją
-- do skasowania. Stąd nazwa `stack_variant`, nie `stack_version` - tamto słowo w repo znaczy już
-- bliźniaki do wyboru, który zostaje.
--
-- KOLUMNY:
--   * `variant_frame_id` (PK) - jeden wariant ma DOKŁADNIE jeden oryginał;
--   * `original_frame_id` - stos, z którego wycięto kadr;
--   * `variant` - słownik rodzajów wariantu; dziś jeden (`autocrop`). Drizzle to ten sam stos
--     w innej skali i do tej tabeli nie należy, dopóki nie przyjdzie dla niego własna decyzja;
--   * `source` - świadek pary, ranga rosnąco `window` < `location` < `user` (lustro
--     `repo.RANGA_WARIANTU`): `window` = jednoznaczne okno `(DATE-OBS, DATE-END, FILTER)` wśród
--     stosów, `location` = dawna lokacja oryginału w tym samym katalogu co autocrop (nazwa bez
--     `_autocrop`), `user` = wskazanie ręką. Automat nie degraduje ręki;
--   * `linked_at` - chwila zapisu relacji (historia zmian w dzienniku `stack_variant.linked`).
--
-- CHECK-i domen: wariant ze słownika, źródło ze słownika, klatka nie jest wariantem samej siebie.
-- UNIQUE(oryginał, wariant): jeden autocrop na oryginał - drugi przycięty kadr tego samego stosu
-- potrzebowałby klucza rozróżniającego, którego dziś nie ma, więc jest konfliktem do ręki.
-- Głębokość 1 (oryginał nie jest wariantem, wariant nie jest oryginałem), rodzaj i aktywność obu
-- klatek oraz obecna kopia oryginału pilnuje klinga `repo.link_stack_variant` - CHECK nie widzi
-- innych wierszy.
CREATE TABLE stack_variant (
    variant_frame_id  INTEGER PRIMARY KEY REFERENCES frame (id),
    original_frame_id INTEGER NOT NULL REFERENCES frame (id),
    variant           TEXT    NOT NULL CHECK (variant IN ('autocrop')),
    source            TEXT    NOT NULL CHECK (source IN ('window', 'location', 'user')),
    linked_at         TEXT    NOT NULL CHECK (length(linked_at) > 0),
    CHECK (variant_frame_id <> original_frame_id),
    UNIQUE (original_frame_id, variant)
);

-- KOLEJKA ZEZNAŃ (`stack_variant_testimony`): zeznanie pary leży jako plik obok kopii wariantu
-- (`projection.write_variant_testimony`), ale Dostawa nie czyta udziału, żeby je znaleźć. Odcisk
-- i treść zeznania zapisuje baza w chwili, gdy zeznanie powstaje albo się zmienia: `apply` planu
-- wersji (zapisał je) i skan (wciągnął kopię wariantu z zeznaniem obok - inna baza, odtworzenie).
-- Konsument relacji pracuje WYŁĄCZNIE na wierszach, których odcisk różni się od skonsumowanego:
--   * `path` - ścieżka pliku zeznania (bez wielkości liter, NTFS);
--   * `fingerprint` - sha1 kanonicznej treści zeznania; nowy odcisk = zeznanie do ponownego odczytu
--     (np. ten sam autocrop z mocniejszym świadkiem oryginału);
--   * `payload` - treść zeznania (JSON), konsument nie wraca do pliku;
--   * `consumed_fingerprint`/`consumed_at`/`outcome` - ostatnie rozstrzygnięcie konsumenta. Wiersz
--     czekający na skan pary (klatki jeszcze nie w bazie) zostaje nierozstrzygnięty.
CREATE TABLE stack_variant_testimony (
    path                 TEXT NOT NULL PRIMARY KEY COLLATE NOCASE CHECK (length(path) > 0),
    fingerprint          TEXT NOT NULL CHECK (length(fingerprint) > 0),
    payload              TEXT NOT NULL,
    recorded_at          TEXT NOT NULL,
    consumed_fingerprint TEXT,
    consumed_at          TEXT,
    outcome              TEXT,
    CHECK ((consumed_fingerprint IS NULL) = (consumed_at IS NULL))
);
