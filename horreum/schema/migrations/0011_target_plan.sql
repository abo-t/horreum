-- 0011 — KURATELA CELÓW + trwały PARK (planer T4; D-0731-4, D-T3-d).
--
-- PRZYROST (CREATE + ADD COLUMN, jak 0004/0006/0010) — zero zmian istniejących tabel i danych.
--
-- Dwa różne fakty użytkownika, oba o PRZYSZŁOŚCI (czym i co zamierza fotografować) — reszta bazy
-- opisuje PRZESZŁOŚĆ (co zebrał). Dlatego żadnego z nich nie da się wyprowadzić z archiwum:
-- `max(date_obs)` wskazałby ED120R (klatki z 2025-05) jako sprzęt aktualny, choć aktualny jest
-- 76EDPH z 2023 (D-0731-12).

-- target_plan: cele, które użytkownik JAWNIE oznaczył. Klucz = kanon rekordu KATALOGU, bo cel
-- mieszka w assecie (plik odświeżalny podmianą), nie w bazie. FK do `object` byłby błędem
-- kategorii: `object` to oś ARCHIWUM (co sfotografowano, append-only, wyłania się z nagłówków —
-- repo.py:576), a cel nigdy nie fotografowany nie ma tam wiersza i mieć go nie powinien (D-0731-4).
-- Zapisywany jest wyłącznie kanon istniejący DZIŚ w katalogu (walidacja: targets.resolve_plan_canon)
-- — literówka tworzyłaby wiersz-widmo, który nigdy nie spotka celu.
CREATE TABLE target_plan (
    canon      TEXT PRIMARY KEY,           -- kanon rekordu katalogu: NGC7000|WR134|G116.9+00.2
    status     TEXT NOT NULL CHECK (status IN ('planned','active','done','skip')),
    priority   INTEGER,                    -- mniejsza = pilniejsza; NULL = bez kolejności
    note       TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- telescope.in_park: trzecie zdanie użytkownika o wierszu osi — obok `label` (etykieta usera) i
-- `status` (proposed|approved). TRÓJSTAN jak `camera.is_mono`: 1 = w parku, 0 = jawnie historyczny,
-- NULL = użytkownik nic nie powiedział. Zlanie NULL z 0 odebrałoby możliwość odróżnienia bazy
-- świeżej od takiej, w której ktoś park przejrzał i świadomie odrzucił ED120R.
-- Brak jakiegokolwiek 1 => planer liczy WSZYSTKIE kanoniczne teleskopy (zachowanie sprzed T4)
-- i mówi o tym wprost. Listy konkretnych teleskopów NIE MA w kodzie ani tutaj — to fakt
-- o archiwum jednego człowieka, a repo jest publiczne (D-0731-12).
ALTER TABLE telescope ADD COLUMN in_park INTEGER;   -- 1 w parku | 0 historyczny | NULL nie zeznano
