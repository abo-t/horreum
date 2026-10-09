-- 0032 - UWAGI KLATKI (WO-2, decyzja D-1009-2): jedna krótka notatka człowieka na klatkę.
--
-- PRZYROST (jedna nowa tabela) - zero przebudowy, zero ruszonych wierszy.
--
-- Opis klatki to jej nagłówki FITS/XISF (droga „Popraw nagłówki”, klinga `writeback.py`) plus JEDNA
-- uwaga, która do pliku nie należy: „chmury po drugiej”, „zmieniony flat”. Żyje wyłącznie w bazie -
-- nagłówek jest zeznaniem kamery i oprogramowania akwizycji, a uwaga jest zdaniem człowieka o nocy;
-- zapis jej do pliku zmieniłby bajty archiwum dla faktu, którego żaden program obróbki nie czyta.
--
-- WIERSZ NA KLATKĘ, nie na lokację: uwaga dotyczy obrazu (tożsamość `sha1_data`), więc wszystkie
-- kopie tej samej klatki mówią to samo, a rename albo przeniesienie pliku jej nie gubią. Klatka
-- zastąpiona (`superseded_by`) zostaje ze swoją uwagą nietkniętą (append-only); na następczynię
-- przenosi ją gest przeniesienia faktów ręki, jak pozostałe osie.
--
-- ZDJĘCIE UWAGI = USUNIĘCIE WIERSZA (z eventem), bez nagrobka: nagrobek chroni decyzję ręki przed
-- automatem, który pisałby to samo pole od nowa (przypisanie obiektu), a uwag żaden automat nie pisze.
-- Precedens: `target_plan` (`repo.clear_target_plan`). Historię niesie dziennik zdarzeń.
--
-- Pisze WYŁĄCZNIE klinga `repo` (z eventem); `updated_at` = chwila ostatniego gestu. CHECK broni
-- pustej treści na poziomie bazy - pusta uwaga to brak uwagi, nie wiersz. `trim` dostaje JAWNY zbiór
-- znaków, bo bez drugiego argumentu SQLite zdejmuje wyłącznie spację, a treść z samych tabulatorów
-- albo końców linii przeszłaby jako uwaga; klinga zwija białe znaki wcześniej, CHECK jest drugą linią.
CREATE TABLE frame_note (
    frame_id   INTEGER PRIMARY KEY REFERENCES frame (id),
    body       TEXT NOT NULL CHECK (length(trim(body, ' ' || char(9) || char(10) || char(11)
                                                     || char(12) || char(13))) > 0),
    updated_at TEXT NOT NULL
);
