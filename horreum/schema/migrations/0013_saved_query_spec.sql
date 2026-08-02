-- Horreum — migracja 0013: PERSPEKTYWY MIESZKAJĄ W BAZIE (segment I-1, paczka P-I).
-- Źródło prawdy: brief/PLAN_pi_martwe_tabele.md §4.3 + decyzja D-P-I-3 (GO Zdzinia 2026-08-01).
--
-- CO SIĘ ZMIENIA I DLACZEGO. `saved_query` z 0002 miała kształt `(name, sql_text)` — nazwany widok
-- zapisany jako SQL. Perspektywa Horreum NIGDY nie była SQL-em: `gui/grid.py` składa ją jako
-- JSON-spec (`filter`, `columns`, `group_by`, `only_dups`, `only_review`, `only_vanished`,
-- `facets`) i trzyma w rejestrze użytkownika. Kolumna `sql_text` nie opisywała więc niczego, co
-- w tym programie istnieje — i nie opisywała tego od pierwszego dnia (zero wierszy, zero pisarzy
-- w `repo.py`).
--
-- D-P-I-3 ODWRACA D-B ŚWIADOMIE: nazwany widok jest własnością ARCHIWUM, nie komputera. Jedzie
-- z bazą na laptop i przeżywa reinstalację; rejestr użytkownika zostaje własnością BIURKA (progi
-- planera, ostatnie katalogi). Koszt zmiany zdania był dziś najniższy, jaki będzie: populacja do
-- migracji = 0 (zmierzone przed decyzją).
--
-- `updated_at` dokładane, bo zapis jest UPSERT-em (kolizja nazw między maszynami — F9): „kiedy
-- powstała" i „kiedy ostatnio nadpisana" to dwa różne fakty i tylko drugi odpowiada na pytanie
-- „czy to jeszcze ta perspektywa, którą zapisałem na stacji".
--
-- STARY WIERSZ NIE GINIE, ALE TEŻ NIE UDAJE SPECYFIKACJI. Gdyby ktoś wpisał wiersz ręcznie
-- (jedyna możliwa droga — pisarza nigdy nie było), jego `sql_text` wędruje do `spec_json` pod
-- kluczem `legacy_sql`. Dwie rzeczy naraz: treść przeżywa, a czytelnik (`queries.perspectives`)
-- rozpoznaje ją jako NIE-specyfikację i odmawia zastosowania zamiast po cichu pokazać „wszystko".
-- Wariant „skopiuj SQL do spec_json bez znacznika" byłby cichym kłamstwem: spec bez znanych kluczy
-- czyta się w GUI jak perspektywa PUSTA, czyli filtr zdejmujący filtr.
--
-- SQLite nie zmienia nazwy ani typu kolumny z NOT NULL ALTER-em → CREATE new + INSERT SELECT +
-- DROP + RENAME (wzorzec 0007/0009/0012). Tabela nie ma dziecka z FK, więc kolejność jest tu
-- zwykłą estetyką, w przeciwieństwie do 0012.

CREATE TABLE saved_query_new (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE,
    spec_json  TEXT NOT NULL,        -- specyfikacja widoku (filter/columns/group_by/facets/…)
    created_at TEXT NOT NULL,
    updated_at TEXT                  -- ostatni upsert; NULL = nigdy nie nadpisana
);

INSERT INTO saved_query_new (id, name, spec_json, created_at)
    SELECT id, name, json_object('legacy_sql', sql_text), created_at FROM saved_query;

DROP TABLE saved_query;
ALTER TABLE saved_query_new RENAME TO saved_query;

PRAGMA user_version = 13;
