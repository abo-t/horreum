-- 0031 - PIKSEL KAMERY Z RĘKI (AR-55 (3)): `camera.pixel_source`.
--
-- PRZYROST (jedna kolumna `ADD COLUMN`) - zero przebudowy tabeli, zero kasowania wierszy.
--
-- Zeznania o pikselu matrycy bywają błędne u źródła: karta `XPIXSZ` flatów SONYA7RM3 niesie 4,86 µm
-- (wartość wpisana w profilu programu akwizycji), EXIF tej kamery 4,62 µm, a matryca ma 4,51-4,52 µm
-- (fakt Zdzinia 2026-10-05). Żadne zeznanie pliku nie jest prawdą - prawdę zna człowiek.
--
-- `pixel_source` = kto ustalił `pixel_um`: NULL - skan (pierwsze zeznanie, uzupełniane CAS-em, rozjazd
-- poza tolerancją = `pixel_conflict`); 'user' - człowiek (`repo.set_camera_pixel`). Wartość z ręki
-- jest SILNIEJSZA od każdego zeznania: skan jej nie zmienia ani nie stawia przy niej konfliktu, a planer
-- (`sky.rigs`) bierze ją przed kartą klatki. Zdjęcie (`repo.clear_camera_pixel`) przywraca stan sprzed
-- wpisu z payloadu eventu `camera.pixel_user_set`.
--
-- BACKFILLU NIE MA: wszystkie wiersze sprzed migracji pochodzą ze skanu (NULL).
-- CHECK odbija „rękę bez piksela": taki wiersz kazałby planerowi odrzucić kartę klatki na rzecz NULL.
ALTER TABLE camera ADD COLUMN pixel_source TEXT
    CHECK (pixel_source IS NULL OR (pixel_source = 'user' AND pixel_um IS NOT NULL));
