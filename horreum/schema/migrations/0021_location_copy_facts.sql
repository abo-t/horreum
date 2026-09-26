-- 0021 - FAKTY KOPII Z JEJ NAGŁÓWKA: liczba i role obrazów + zeznanie nagłówka TEJ kopii (location).
--
-- PRZYROST (ADD COLUMN, jak 0017..0020) - zero zmian istniejących kolumn, zero wierszy ruszonych.
-- Kolumny WCHODZĄ PUSTE. Wypełnia je klinga kopii (`repo.add_location` / `repo.refresh_location`)
-- przy każdym odczycie pliku, a dla wierszy sprzed migracji - osobna faza uzupełnienia
-- (`scan.backfill_copy_facts`, etap Dostawy), NIE ta migracja i NIE resolver: fakty są w pliku,
-- a SQL ich nie zna.
--
-- DLACZEGO NA KOPII, A NIE NA KLATCE. Tożsamość klatki XISF to sha1 bajtów attachmentu PIERWSZEGO
-- `<Image>` (`scan.read_xisf_meta_full`), więc dwie kopie jednej klatki mogą się różnić wszystkim
-- poza pikselami pierwszego obrazu: nagłówkiem (FILTER=CLS obok FILTER=L-Pro) i liczbą obrazów
-- (integracja z mapami odrzuceń obok samej integracji). Tabela `header` trzyma JEDNO zeznanie na
-- klatkę (pierwsza wciągnięta kopia, potem ta, której odcisk zmienił się ostatnio - `refresh_location`),
-- a kopia miała dotąd tylko `header_hash`: baza wiedziała, ŻE nagłówki się różnią, nie wiedziała CZYM.
-- Zmierzone 2026-09-26: 5 klatek z >1 obecną kopią, w tym 3 z różnym `header_hash`.
--
-- LICZBA I ROLE OBRAZÓW (XISF; FITS i RAW - NULL):
--   * `image_count` - ile `<Image>` deklaruje nagłówek XML tej kopii (wszystkie, w kolejności
--     dokumentu, niezależnie od `location`);
--   * `image_roles` - lista JSON długości `image_count`: rola = `imageType` (§11.5.1), a gdy go brak -
--     `id`; `null`, gdy obraz nie niesie żadnego. Zmierzone 2026-09-26 na 550 obecnych plikach:
--     230 ma >1 obraz, `imageType` stoi wyłącznie w części plików wieloobrazowych, a 248 obrazów
--     (pojedynczych) nie ma ani `imageType`, ani `id`.
--   Lista, nie tabela potomna: rola nie ma własnej tożsamości ani pisarza, a pytanie brzmi zawsze
--   „co niesie TA kopia" - jeden wiersz, jedna odpowiedź. Dwie kolumny, choć liczba wynika z listy,
--   bo liczba jest faktem, po którym się sortuje i porównuje kopie; zgodność obu pilnuje CHECK
--   (długość listy == liczba, obie albo żadna), więc dwie postaci jednego faktu nie mają jak się
--   rozjechać.
--   FITS dostaje NULL świadomie: czytnik zatrzymuje się na pierwszym HDU z obrazem (`_select_hdu`),
--   a astropy ładuje HDU leniwie - policzenie wszystkich wymagałoby przeczytania nagłówków każdego
--   HDU za blokami danych, czyli DODATKOWEGO I/O na 15,6 tys. plików. RAW: czytnik EXIF czyta
--   tagi, nie strukturę obrazów pliku (podglądy, miniatury) - liczba byłaby wnioskiem, nie odczytem.
--
-- ZEZNANIE NAGŁÓWKA KOPII (`hdr_*`): pola, które karmią OŚ klatki albo wybór po wartości -
--   FILTER (oś filtra, przepis flata), IMAGETYP (rodzaj), OBJECT (oś obiektu), TELESCOP (oś
--   teleskopu, przepis flata), INSTRUME (oś kamery), EXPTIME (godziny portfela, przepis darka),
--   XBINNING (przepis kalibracji), DATE-OBS (noc, okno rodowodu stosu, najbliższy flat w czasie).
--   Rozjazd któregokolwiek znaczy, że oś klatki zależy od tego, która kopia wygrała w `header`.
--   Świadomie POZA: GAIN/OFFSET/SET-TEMP (mastery ich nie niosą - 0/111; przepis darka czyta je ze
--   ścieżki), RA/DEC (region - liczba z szumem formatowania, rozjazd bez znaczenia dla osi).
--   Wartości przez TĘ SAMĄ koercję co pola gorące `header` (`resolve.headers.extract_header`): XISF
--   przynosi TEKST, FITS liczby, a porównanie kopii bez rzutu widziałoby rozjazd '1.34' vs 1.34.
--   To częściowo powtarza `header` dla kopii, która wygrała - świadomy koszt: `header` jest
--   zeznaniem KLATKI (jedno), tu stoi zeznanie KAŻDEJ kopii, a innej drogi do niego nie ma
--   (`cards` są per klatka, surowego nagłówka kopii baza nie trzyma).
--
-- KOTWICA `hdr_hash` - odcisk nagłówka, z którego pochodzą wszystkie fakty tej migracji. Znaczy
-- „fakty opisują nagłówek o tym odcisku"; NULL = jeszcze nie zebrane. CHECK `hdr_hash = header_hash`
-- zamyka całą klasę zwietrzałych faktów: pisarz, który zmieni odcisk kopii i nie odświeży jej faktów,
-- dostaje IntegrityError zamiast cichej nieprawdy. Drugi CHECK wiąże fakty z kotwicą (fakt bez
-- kotwicy = sprzeczność, wzorzec 0019). `IS`, nie `=`: CHECK przepuszcza wynik NULL, więc `=`
-- wpuściłby kotwicę przy kopii BEZ odcisku (`'h' = NULL` daje NULL, nie fałsz) - złapane testem
-- `test_0021_CHECK_kotwica_i_para_obrazow`. Sprawdzone jak przy 0019/0020: SQLite przyjmuje na
-- ADD COLUMN CHECK-i przez inne kolumny tego samego wiersza i testuje je na istniejących wierszach
-- (wszystkie nowe kolumny NULL - przechodzą).
--
-- STRAŻNIKI TYPU na dwóch kolumnach liczbowych: baza jest ostatnią bramką W3 - tekst, który
-- przeszedłby obok koercji, rozdzieliłby porównanie kopii tak samo, jak kiedyś rozdzielił kamery.
ALTER TABLE location ADD COLUMN image_count INTEGER
    CHECK (image_count IS NULL OR image_count >= 0);
ALTER TABLE location ADD COLUMN image_roles TEXT
    CHECK ((image_roles IS NULL AND image_count IS NULL)
           OR (image_roles IS NOT NULL AND image_count IS NOT NULL
               AND json_valid(image_roles) AND json_type(image_roles) = 'array'
               AND json_array_length(image_roles) = image_count));
ALTER TABLE location ADD COLUMN hdr_filter TEXT;
ALTER TABLE location ADD COLUMN hdr_imagetyp TEXT;
ALTER TABLE location ADD COLUMN hdr_object TEXT;
ALTER TABLE location ADD COLUMN hdr_telescop TEXT;
ALTER TABLE location ADD COLUMN hdr_instrume TEXT;
ALTER TABLE location ADD COLUMN hdr_exptime REAL
    CHECK (hdr_exptime IS NULL OR typeof(hdr_exptime) = 'real');
ALTER TABLE location ADD COLUMN hdr_xbinning INTEGER
    CHECK (hdr_xbinning IS NULL OR typeof(hdr_xbinning) = 'integer');
ALTER TABLE location ADD COLUMN hdr_date_obs TEXT;
ALTER TABLE location ADD COLUMN hdr_hash TEXT
    CHECK (hdr_hash IS NULL OR hdr_hash IS header_hash)
    CHECK (hdr_hash IS NOT NULL
           OR (image_count IS NULL AND image_roles IS NULL AND hdr_filter IS NULL
               AND hdr_imagetyp IS NULL AND hdr_object IS NULL AND hdr_telescop IS NULL
               AND hdr_instrume IS NULL AND hdr_exptime IS NULL AND hdr_xbinning IS NULL
               AND hdr_date_obs IS NULL));
