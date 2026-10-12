-- 0039 - OPTYKA TELESKOPU Z RĘKI (AR-128, D-1012-1, D-1012-2): `telescope.focal_user`, `f_ratio_user`.
--
-- PRZYROST (dwie kolumny `ADD COLUMN`) - zero przebudowy tabeli, zero kasowania wierszy.
--
-- Ogniskowa i f/ teleskopu mają odtąd DWA miejsca, każde z innym autorem:
--   * `focal_nominal`/`f_ratio_nominal` - wartość Z PLIKÓW: moda zeznań aktywnych lightów (bez nich -
--     flatów) zestawów teleskopu i jego członków scalenia, odświeżana przy każdej Dostawie
--     (`grouper.optics_from_files` + `repo.refresh_telescope_optics`). Dawniej: pierwsza klatka grupy,
--     zapisana raz i nigdy nieodświeżana (A140R pokazywał f/8.0 przy 7370 klatkach f/5.6);
--   * `focal_user`/`f_ratio_user` - wartość RĘKI (`repo.set_telescope_focal`/`set_telescope_f_ratio`
--     i okno „Dopisz nowy…”). Ręka wygrywa przy KAŻDYM odczycie (oś, planer, kubełki), automat jej
--     nie czyta i nie pisze. Cofnięcie ręki = NULL w jej kolumnie; wartość z plików stoi obok.
--
-- BACKFILL RĘKI: teleskop powołany ręką (`telescope.proposed` z aktorem `user:%`) niesie w kolumnach
-- automatu zdanie człowieka. Bez przeniesienia pierwsza Dostawa z zeznaniem tej nazwy nadpisałaby je
-- modą z plików, a spis ręki by tego nie zobaczył. Wartość bierzemy z PAYLOADU zdarzenia (to wpisała
-- ręka), nie z bieżącej kolumny. Na żywym archiwum: jeden wiersz (RC8R, 1200 mm). Każdy przeniesiony
-- fakt dostaje zdarzenie `telescope.focal_user_set`/`f_ratio_user_set` z pochodzeniem w `via`, żeby
-- Historia osi i spis ręki znały jego źródło; `via` wskazuje zdarzenie wybrane TYM SAMYM warunkiem co
-- wartość (najstarsze `proposed` ręki z dodatnią wartością tego pola).
--
-- WARTOŚĆ Z PLIKÓW liczy się zaraz po tej migracji (`db.open_db` → `grouper.refresh_all_optics`),
-- nie dopiero przy pierwszej Dostawie: kolumna automatu niosła dotąd wartość PIERWSZEJ klatki, a od
-- niej zależą kubełek f/ i cel gestu naprawy plików (bramka kodu T24, N1). SQL tej derywacji nie
-- powtarza - ma jednego właściciela w Pythonie.
ALTER TABLE telescope ADD COLUMN focal_user REAL CHECK (focal_user IS NULL OR focal_user > 0);
ALTER TABLE telescope ADD COLUMN f_ratio_user REAL CHECK (f_ratio_user IS NULL OR f_ratio_user > 0);

UPDATE telescope SET
    focal_user = (SELECT CAST(json_extract(e.payload, '$.focal_nominal') AS REAL) FROM event e
                   WHERE e.verb = 'telescope.proposed' AND e.actor LIKE 'user:%'
                     AND e.target = 'telescope:' || telescope.id
                     AND json_extract(e.payload, '$.focal_nominal') > 0
                   ORDER BY e.id LIMIT 1),
    f_ratio_user = (SELECT CAST(json_extract(e.payload, '$.f_ratio_nominal') AS REAL) FROM event e
                     WHERE e.verb = 'telescope.proposed' AND e.actor LIKE 'user:%'
                       AND e.target = 'telescope:' || telescope.id
                       AND json_extract(e.payload, '$.f_ratio_nominal') > 0
                     ORDER BY e.id LIMIT 1)
WHERE EXISTS (SELECT 1 FROM event e WHERE e.verb = 'telescope.proposed' AND e.actor LIKE 'user:%'
                AND e.target = 'telescope:' || telescope.id);

INSERT INTO event (ts, actor, verb, target, payload, reason)
    SELECT strftime('%Y-%m-%dT%H:%M:%f+00:00', 'now'), 'migration:0039', 'telescope.focal_user_set',
           'telescope:' || t.id,
           json_object('after', t.focal_user, 'before', NULL, 'via',
                       'proposed:' || (SELECT min(e.id) FROM event e WHERE e.verb = 'telescope.proposed'
                                         AND e.actor LIKE 'user:%' AND e.target = 'telescope:' || t.id
                                         AND json_extract(e.payload, '$.focal_nominal') > 0)),
           'wartość ręki z chwili powołania teleskopu przeniesiona do kolumny ręki'
      FROM telescope t WHERE t.focal_user IS NOT NULL;

INSERT INTO event (ts, actor, verb, target, payload, reason)
    SELECT strftime('%Y-%m-%dT%H:%M:%f+00:00', 'now'), 'migration:0039', 'telescope.f_ratio_user_set',
           'telescope:' || t.id,
           json_object('after', t.f_ratio_user, 'before', NULL, 'via',
                       'proposed:' || (SELECT min(e.id) FROM event e WHERE e.verb = 'telescope.proposed'
                                         AND e.actor LIKE 'user:%' AND e.target = 'telescope:' || t.id
                                         AND json_extract(e.payload, '$.f_ratio_nominal') > 0)),
           'wartość ręki z chwili powołania teleskopu przeniesiona do kolumny ręki'
      FROM telescope t WHERE t.f_ratio_user IS NOT NULL;
