# Horreum - instrukcja obsługi

*Dla osoby, która pobrała Horreum z GitHuba i chce zapanować nad własnym archiwum astrofoto - bez
znajomości programowania. Horreum robi cztery rzeczy i każda ma swój kafel na pierwszym ekranie:
**Przyjmij** nowe klatki do katalogu, **Znajdź** to, czego potrzebujesz, **Wydaj do WBPP** komplet
obiektu do obróbki w PixInsight, **Popraw** to, czego automat nie był pewny. Wszystko inne leży pod
**Więcej…**. Ta instrukcja idzie tą samą drogą: najpierw o co w tym chodzi, potem po jednej części na
każdy kafel.*

---

## Zanim zaczniesz - o co w tym chodzi

Wyobraź sobie **bibliotekarza**, który nie przestawia Twoich książek, tylko robi im **katalog**.
Horreum działa tak z Twoimi klatkami FITS i XISF. Pracujesz z trzema miejscami:

| Miejsce | Pytanie, na które odpowiada | Przykład |
|---|---|---|
| **Archiwum** | Gdzie leżą moje zdjęcia na zawsze? | `R:\ASTRO_` z podfolderami `LIGHTS`, `CALIBRATION`, `STACKS` |
| **Baza** | Co Horreum wie o tych zdjęciach? | jeden plik, np. `astro.db` |
| **Folder roboczy WBPP** | Gdzie przygotować materiał do jednej obróbki? | `R:\ASTRO_\_WBPP` - Horreum zakłada go sam |

- **Twoje pliki w archiwum zostają tam, gdzie są.** Przyjmowanie klatek tylko czyta **nagłówek**
  każdego pliku (dane zapisane przez program akwizycyjny) i wpisuje je do bazy. Niczego nie przenosi,
  nie zmienia nazw i nie kasuje.
- **Baza to Twój katalog** - źródło prawdy, nie układ folderów. Jedna baza wystarcza na całe archiwum.
- **Tożsamością klatki jest jej zawartość, nie nazwa ani ścieżka.** Przeniesiesz albo przemianujesz
  plik - Horreum rozpozna tę samą klatkę i nie zrobi duplikatu.
- **Nic się nie nadpisuje.** Każda zmiana to dopisek do historii, więc widać, co i kiedy się stało,
  a gesty ręki da się cofnąć.
- **Folder roboczy WBPP to stół, nie półka.** Leżą tam linki do klatek z archiwum, ułożone tak, jak
  lubi WBPP. Po obróbce wyniki wracają do archiwum, a folder roboczy możesz skasować.

Horreum sam wyprowadza z nagłówków **trzy osie**, po których szukasz zdjęć:

- **teleskop** - jakim sprzętem robione (pole `TELESCOP`),
- **stanowisko** - skąd obserwowane (współrzędne GPS w nagłówku),
- **obiekt** - co jest na zdjęciu (katalogi Messier, NGC, IC, nazwy potoczne, ciała Układu Słonecznego).

Do tego dochodzi Twoja **uwaga** - jedno krótkie zdanie na klatce („chmury po 2:00"), które trzyma
baza, nigdy plik.

Cykl pracy z jednym obiektem wygląda tak:

    1. Przyjmij          nowa noc trafia do katalogu        (kafel Przyjmij)
    2. Znajdź            co mam z tego obiektu?             (kafel Znajdź)
    3. Wydaj do WBPP     komplet obiektu na stół            (kafel Wydaj do WBPP)
    4. WBPP              obróbka w PixInsight               (poza Horreum)
    5. Wciągnij z WBPP   nowe mastery i stosy do archiwum   (Więcej… na Domu albo Dostawa, sekcja Stosy)
    6. Popraw            to, czego automat nie był pewny    (kafel Popraw)

Kroki 1, 2 i 6 robisz po każdej sesji. Kroki 3-5 wtedy, gdy siadasz do obróbki.

---

## Ekran Dom

Po otwarciu bazy widzisz ekran **Dom** z pytaniem **Co chcesz zrobić?** i czterema kaflami:

    Menu:  Plik                          Widok
           Otwórz bazę… / Nowa baza…     Ciemny / Jasny
           Folder roboczy WBPP…          Polski / English

    +-----------------------+------------------------------------------------------+
    | Dom                   |  Co chcesz zrobić?                        [Więcej…]  |
    | Znajdź                |                                                      |
    | Więcej                |  [Przyjmij] [Znajdź] [Wydaj do WBPP] [Popraw · 3]    |
    |   Dostawa             |                                                      |
    |   Zbiory klasyczne    |  Co mam: 73 obiekty · 14338 lightów · ... · 124 noce |
    |   Porządki            |                                                      |
    |   Planer              |  Teczki - najwięcej godzin                           |
    |                       |  [● NGC7000] [● IC1795] [● M31] ...                  |
    |                       |                                                      |
    |                       |  Ostatnio (04.10): ...          [droga powrotu]      |
    +-----------------------+------------------------------------------------------+

| Element | Co mówi i dokąd prowadzi |
|---|---|
| **Przyjmij** | od razu uruchamia przyjęcie nowych klatek i pokazuje raport (część „Przyjmij") |
| **Znajdź** | jedno pole do szukania po obiekcie, nocy, filtrze, teleskopie, zestawie i uwagach |
| **Wydaj do WBPP** | lista obiektów z gotowością kalibracji; wybrany obiekt idzie na stół WBPP |
| **Popraw** | lista zadań w **Porządki**; cyfra na kaflu (**Popraw · 3**) to ta sama liczba, co przy **Porządki (3)** |
| **Co mam:** | ile masz obiektów, lightów, godzin i nocy oraz datę ostatniej nocy |
| **Teczki - najwięcej godzin** | do osiemnastu kart obiektów z największym dorobkiem; klik w kartę pokazuje klatki tego obiektu w **Znajdź** |
| **Ostatnio** | Twój ostatni gest (np. przypisanie obiektu, uwaga) i przycisk, który go cofa |
| **Więcej…** | **Wciągnij z WBPP…**, planer, mapa stanowisk, nazwy plików, makra nagłówków, perspektywy, tryb zaawansowany, **Zbiory klasyczne** |

Karta teczki ma **kropkę stanu kalibracji**: zielona - każdy light ma master flat i master dark,
bursztynowa - części brakuje, czerwona - żaden light nie ma ani flatu, ani darka. Pod nazwą stoi
procent lightów z flatem (osobno z surowymi flatami) i z darkiem. Linia „… do przeliczenia
w Dostawie" znaczy, że master już jest, a brakuje tylko przeliczenia - to jedno kliknięcie, nie braki
w materiale.

> Gdy teczek jest więcej, niż mieści okno, pod kartami stoi „… i N kolejnych - szukaj w Znajdź".
> Wyższe okno pokazuje więcej rzędów kart.

Pasek boczny z lewej daje te same miejsca bez Domu: **Dom**, **Znajdź**, a pod szarym napisem
**Więcej** - **Dostawa**, **Zbiory klasyczne**, **Porządki** i **Planer**.

---

## Uruchomienie i baza

### Wersja gotowa czy ze źródła?

**Jedno pytanie:** czy masz Windows i chcesz po prostu kliknąć, żeby ruszyło? Jeśli tak - wersja gotowa.

| | Kiedy | Co robisz |
|---|---|---|
| **Wersja gotowa** (zalecana) | Windows, bez instalowania czegokolwiek | Pobierasz z **Releases** jeden plik **`Horreum-<wersja>-windows-x64.exe`** i klikasz go dwa razy |
| **Ze źródła** | Linux/Mac albo najnowszy kod | W folderze projektu: `pip install -e ".[gui]"`, potem `python -m horreum.gui` |

Koszt pomyłki jest zerowy - obie wersje działają na tej samej bazie.

> **Pierwsze uruchomienie wersji gotowej trwa kilka sekund.** Okno mówi, co robi („Otwieram bazę…",
> „Buduję widoki…") - jeśli coś pisze, to pracuje. Windows może ostrzec, że to nieznana aplikacja;
> wybierz **Więcej informacji → Uruchom mimo to**. Numer wersji stoi w **tytule okna**.

### Załóż bazę (raz)

1. Menu **Plik → Nowa baza…**
2. Wskaż miejsce i nazwę pliku.

| Pole | Co wpisać |
|---|---|
| Nazwa pliku | krótko, bez spacji: np. `astro.db` |
| Miejsce | tam, gdzie łatwo trafisz - np. obok archiwum |

**Co program zrobi sam:** założy pustą bazę, pokaże pasek boczny i ekran **Dom**. Pusta baza to
normalny stan - Dom mówi wtedy „Co mam: jeszcze żadnego lightu z obiektem - zacznij od „Przyjmij”."
Przy następnym starcie program sam wróci do ostatniej bazy. Inną otworzysz przez **Plik → Otwórz bazę…**.

### Wskaż folder roboczy WBPP (raz)

1. Menu **Plik → Folder roboczy WBPP…**
2. Wskaż katalog, w którym ma powstawać stół do obróbki - np. `R:\ASTRO_`.

**Co program zrobi sam:** dopisze do wskazanego katalogu podfolder `_WBPP` (tu: `R:\ASTRO_\_WBPP`),
zapamięta go jako cel wydania o nazwie **Folder roboczy** i stąd będzie brał wyniki WBPP. Na dysku nic
jeszcze nie powstaje - folder założy pierwsze wydanie.

> Wybierz katalog **na tym samym dysku co archiwum**. Wtedy wydanie robi linki, które nie zajmują
> miejsca. Na innym dysku Horreum musiałby kopiować pliki. Folder `_WBPP` jest pomijany przy
> przyjmowaniu klatek, więc stół nigdy nie wraca do katalogu jako druga kopia archiwum.

---

## Przyjmij - wpuść nowe klatki do katalogu

**Po co:** po każdej nocy chcesz, żeby nowe klatki znalazły się w katalogu, dostały obiekt,
stanowisko i kalibrację.

1. Na **Dom** kliknij **Przyjmij**.
2. Przy **pierwszym** przyjęciu program zapyta o katalog - wskaż **główny katalog archiwum**
   (np. `R:\ASTRO_`). Horreum zejdzie sam w dowolnie zagnieżdżone podfoldery.
3. Poczekaj. Pasek postępu pokazuje, ile plików przeszło. Pierwsze przyjęcie dużego archiwum trwa
   minuty - to jednorazowy koszt.

Kafel prowadzi na stronę **Dostawa** i od razu uruchamia jej złotą akcję **Przyjmij nowe**. Następnym
razem program pamięta katalog i nie pyta.

**Co dzieje się po kolei, jednym kliknięciem:**

| Etap | Co się dzieje |
|---|---|
| skan | czyta nagłówki plików i wpisuje klatki do bazy (nic nie zmienia na dysku) |
| fakty kopii | zbiera, co mówi każda kopia pliku, gdy klatka leży w kilku miejscach |
| grupuj | ustala teleskopy i zestawy sprzętu (teleskop × kamera) |
| rozwiąż | rozpoznaje obiekty, stanowiska i filtry |
| kalibracja | dobiera do lightów pasujące mastery flat i dark |
| delta | podsumowuje, co przyszło i co czeka na Twoją decyzję |

### Raport „Co przyszło"

Nad przyciskami Dostawy pojawia się panel **Co przyszło**:

- „Dostawa z 08:15: 312 nowych klatek (lighty 280 · flaty 30 · mastery 2)" - co weszło do bazy,
- „Obiekty: NGC7000 ×200 (3.3 h) · IC1795 ×80 (1.3 h)" - na co,
- „Kalibracja nowych lightów: flat master 250 · surowy flat 30 · dark master 280" - czym je skalibrujesz,
- **Nie rozpoznałem: N klatek** albo **Wszystko rozpoznane**.

Pod „Nie rozpoznałem" stoi wiersz na każdą nierozpoznaną nazwę z nagłówka, np. „„Ameryka” ×40
w tej dostawie", z przyciskiem **Przypisz obiekt…**. Wskaż w oknie, czym ta nazwa jest naprawdę
(np. `NGC 7000`) i zatwierdź. Pasek stanu odpowie:

    Zapamiętałem: „Ameryka” = NGC7000 - następne dostawy rozpoznają same

To jest cała nauka programu: od tej chwili ta nazwa w nagłówku zostaje rozpoznana bez pytania.
Wiersze klatek **bez nazwy w nagłówku**, **RAW bez nazwy** i **stosy bez nazwy** mają przycisk
**Porządki** - prowadzi prosto do właściwej naprawy (część „Popraw").

> **To bezpieczne.** Przyjmowanie tylko **czyta** pliki. Możesz je uruchamiać wielokrotnie - pliki,
> które Horreum już zna, są pomijane, więc kolejne przyjęcia trwają sekundy.

### Gotowe obrazy z drzewa obróbki (stosy)

Na dole strony Dostawy jest sekcja **Stosy**. Gotowe obrazy po integracji (stosy) leżące poza
archiwum, w Twoim drzewie obróbki, dodasz przyciskiem **Wciągnij stosy…** - wskaż korzeń drzewa.
Horreum bierze **wyłącznie pliki `masterLight*.xisf`** razem z ich wariantami obrazu: skadrowanym
(`_autocrop`) i przeskalowanym (`_drizzle_1x`). Pomija dalsze kroki obróbki: po usunięciu gradientu
(`_ABE`, `_DBE`), po kalibracji koloru (`_SPCC`), bez gwiazd (`_starless`) i podobne - także
doklejone do wariantu (`_autocropSPCC`). To nie są osobne zdjęcia, tylko obróbka jednego obrazu.

> Ta droga tylko **czyta** - w drzewie obróbki nie zmienia się ani jeden bajt. Stosy, które leżą
> w archiwum w folderze `STACKS`, przyjmuje zwykłe **Przyjmij nowe** - nie musisz ich wciągać osobno.

**Horreum zapisuje, z czego powstał każdy stos** (rodowód): szuka w bazie klatek, które do niego
weszły. Dzięki temu widzisz, ile godzin naprawdę siedzi w gotowym obrazie, a nie tylko ile klatek
masz na dysku.

---

## Znajdź - wyszukaj to, czego potrzebujesz

**Po co:** chcesz zobaczyć wszystko z jednego obiektu, z jednej nocy albo z jednym filtrem - bez
przeklikiwania folderów.

1. Na **Dom** kliknij **Znajdź** - kursor stoi już w polu.
2. Wpisz pytanie i naciśnij Enter.

| Wpisujesz | Dostajesz |
|---|---|
| `Ameryka Północna`, `NGC 7000`, `ngc7000` | klatki tego obiektu - nazwa potoczna i katalogowa trafiają tak samo |
| `noc:2026-08` | klatki z nocy sierpnia 2026 (działa też `noc:2026` i `noc:2026-08-08`) |
| `filtr:Ha,OIII` | klatki z filtrem Ha **albo** OIII |
| `teleskop:askar` | klatki z tego teleskopu (wystarczy początek nazwy) |
| `zestaw:<teleskop>_<kamera>` | klatki z jednego zestawu sprzętu |
| `uwagi:chmury` | klatki, których uwaga zawiera to słowo |
| `NGC 7000 noc:2026-08 filtr:Ha` | wszystkie warunki naraz |

Słowo, które nie jest nazwą żadnego obiektu, szuka w uwagach. Wartość ze spacją weź w cudzysłów.
Prefiksy angielskie (`night:`, `filter:`, `telescope:`, `setup:`, `notes:`) działają zawsze.

**Co widzisz po Enterze:**

- **chipy** nad tabelą - po jednym na wpisany warunek, np. „Noc: 2026-08  ×". Klik w chip zdejmuje
  ten warunek ze zbioru;
- tabelę z prostym zestawem kolumn: **Obiekt**, **Noc**, **Filtr**, **Czas**, **Zestaw**, **Uwagi**, **Plik**;
- zdanie „Nie znam: … - reszta zapytania działa.", gdy część pytania nie pasuje do archiwum (np.
  literówka). Gdy nie pasuje nic, zbiór zostaje bez zmian i zdanie mówi to wprost.

Pod tabelą stoi pasek czasowników na tym, co znalazłeś: **Wydaj do WBPP**, **Popraw nagłówki…**,
**Obiekt** (menu), **Rodowód…**, **Uwagi…**, **Kolumny** i **Zbiory klasyczne**. Licznik po lewej mówi,
ile klatek jest w zbiorze i ile zaznaczyłeś.

> **Zaznaczenie to Twój warsztat.** Gesty zapisu działają na tym, co **zaznaczysz**, nigdy na całej
> widocznej liście. Klik, `Ctrl` i `Shift` jak w Eksploratorze.

### Co mówi kolumna „Obiekt"

Ta kolumna niesie **pięć różnych odpowiedzi**, a każda ma inną receptę. Znacznik przed nazwą mówi,
skąd nazwa się wzięła i czy jest tu dla Ciebie robota. To samo wyjaśnienie dostaniesz po najechaniu
myszą na komórkę.

| Co widzisz | Co to znaczy | Co z tym zrobić |
|---|---|---|
| `NGC7000` - zwykła nazwa | obiekt rozpoznany, nazwa jest w bazie na stałe | nic, to stan docelowy |
| `↺ NGC7000` | nazwa była przypisana, ale **Twoja ręka ją zdjęła**; program pamięta, co zdjął | pomyłka: **Obiekt → Przywróć cofnięte przypisanie**; świadoma decyzja: zostaw, program sam jej nie przywróci |
| `? Mgławica Ameryka` | w pliku jest nazwa, której **program nie rozpoznał** - jedyny stan, który JEST robotą | **Obiekt → Przypisz obiekt…** (decyzja w bazie) albo **Napraw nagłówek…** w Porządkach (nazwa idzie do pliku) |
| `⟨NGC7000⟩` w nawiasach kątowych | **podpowiedź z nazwy folderu**, nie fakt z pliku | potwierdź ją (**Zatwierdź ze ścieżki…** w Porządkach) albo nadaj nazwę przez **Obiekt → Przypisz obiekt…** |
| `dark`, `flat` - szarą kursywą, bez znacznika | klatka **kalibracyjna** - obiektu nie ma z definicji | nic, dlatego program to wygasza |

Pusta komórka znaczy dokładnie tyle: plik nie mówi nic o obiekcie, a program niczego nie zgaduje.

### Uwagi - Twoje zdanie na klatce

Uwaga to jedno krótkie zdanie (do 300 znaków), np. „chmury po 2:00" albo „zmieniony flat".
Leży w bazie, **nigdy w pliku**, i przeżywa każde kolejne przyjęcie.

1. Zaznacz klatki w **Znajdź**.
2. Kliknij **Uwagi…** (w **Zbiory klasyczne**: menu **Klatka → Uwagi…**).
3. W oknie **Uwagi klatek** wpisz treść i kliknij **Zapisz**. **Usuń uwagi** zdejmuje je z zaznaczenia.

Okno mówi, ile zaznaczonych klatek ma już uwagę. Gdy mają różne, zapis zastąpi je jedną. Pomyłkę
cofniesz przyciskiem **Cofnij uwagi** na pasku stanu albo w wierszu „Ostatnio" na Domu. Uwagę
znajdziesz potem, wpisując w **Znajdź** jej słowo albo `uwagi:…`.

### Rodowód - z czego powstał obraz

Zaznacz **jedną** klatkę i kliknij **Rodowód…**. Dla gotowego obrazu panel pokaże, z jakich klatek
powstał i ile to godzin. Dla klatki nieba - czym ją skalibrowano (który master flat i dark).
Wejścia stosu możesz potwierdzić albo odrzucić (**Potwierdź zaznaczone**, **Odrzuć zaznaczone**).

---

## Wydaj do WBPP - przygotuj obiekt do obróbki

**Po co:** siadasz do obróbki jednego obiektu i chcesz dać WBPP komplet - lighty, mastery
kalibracyjne i surowe flaty tam, gdzie mastera brak - bez ręcznego zbierania plików z dziesięciu
folderów.

**Model:** wydanie to **stół**, nie przeprowadzka. Horreum układa w folderze roboczym drzewo **linków**
do plików archiwum. Archiwum zostaje nietknięte, a skasowanie stołu nie kasuje żadnego zdjęcia.

    R:\ASTRO_\_WBPP\OBJECTS\NGC7000\
        <zestaw>\LIGHT\<filtr>\       lighty obiektu
        <zestaw>\MASTER\flat\         mastery flat dobrane do tych lightów
        <zestaw>\MASTER\dark\         mastery dark
        <zestaw>\FLAT_RAW\<filtr>\    surowe flaty, gdy mastera flat brak
        out\                          tu WBPP odda wyniki
        _PROJEKCJA.json               zapis, co dokładnie wydano

### Krok po kroku

1. Na **Dom** kliknij **Wydaj do WBPP**.
2. Okno **Wybierz obiekt do wydania** pokazuje listę obiektów: kropka stanu, **Obiekt**, **Godz.**,
   **Lightów**, **Nocy**, **Zestawów**, **Flat (master / surowy)**, **Dark**, **Ostatnia noc**.
   Wpisz nazwę w pole **Szukaj:**, zaznacz obiekt i kliknij **Dalej** (albo dwuklik).
3. Okno **Wydaj obiekt do WBPP** liczy podgląd samo - na dysku jeszcze nic nie powstaje.

| Pole | Co wybrać |
|---|---|
| **Cel wydania:** | karta **Folder roboczy** (zapamiętana z menu **Plik**); inny cel dodasz przez **+ inny cel…** - musi leżeć pod folderem `_WBPP` albo `_Review` |
| **Zestaw:** | **Wszystkie** albo jeden zestaw, gdy chcesz obrabiać tylko materiał z jednego teleskopu i kamery |
| **Wymuś kopię bajtów** | zostaw puste; zaznacz tylko wtedy, gdy linki przez sieć zawodzą |

4. Przeczytaj podgląd. Nagłówek mówi, co wyjeżdża, np. „NGC7000: 556 lightów · 7 masterów · 120
   surowych flatów · bez flatu 0 · bez darka 556". Pod nim rozbicie na zestawy i powody braków.
5. Kliknij złoty przycisk **Utwórz N linków** (przy innym dysku: **Utwórz N kopii**).
6. Po wydaniu kliknij **Otwórz w Eksploratorze**. Pod podglądem stoi **Wyjście WBPP:** ze ścieżką
   do folderu `out` i przycisk **Kopiuj ścieżkę**.

> **Ostrzeżenie, nie blokada:** „bez flatu" i „bez darka" w podglądzie nie zatrzymują wydania.
> Mówią, że części lightów WBPP nie skalibruje w pełni. Powód stoi obok, np. „najbliższe surowe flaty
> dalej niż 30 dni" albo „master jest, rodowód go nie przeliczył" - to drugie naprawia jedno
> przyjęcie w Dostawie.

**Co program zrobi sam:**

- dobierze mastery z kalibracji lightów; gdy mastera flat brak - surowe flaty tej samej nastawy
  z tej samej nocy, a gdy ich nie ma - z najbliższej nocy w oknie 30 dni,
- ten sam dysk co archiwum - zrobi linki (zero miejsca), inny dysk - kopie,
- zapisze `_PROJEKCJA.json`, czyli co dokładnie wydał (z tego korzysta potem **Wciągnij z WBPP…**),
- przy drugim wydaniu tego samego obiektu dołoży tylko to, czego na stole brakuje.

### W PixInsight (WBPP)

1. W WBPP dodaj folder obiektu (**Add Directory** na `…\_WBPP\OBJECTS\NGC7000`).
2. Ustaw **Output Directory** na ścieżkę z **Kopiuj ścieżkę** (folder `out`).
3. Jedna sesja WBPP na jedno wydanie. Gdy mieszasz wydania, dodaj keyword `TELESCOP` jako Pre i Post.

### Po WBPP: Wciągnij wyniki do archiwum

**Po co:** WBPP zbudował nowe mastery flat i stosy. Chcesz, żeby trafiły do archiwum pod porządną
nazwą, a archiwum wiedziało, z czego powstały.

1. Na Domu wybierz **Więcej… → Wciągnij z WBPP…** (albo na stronie **Dostawa** w sekcji **Stosy**
   kliknij **Wciągnij z WBPP…**).
2. Okno **Wciągnij wyniki WBPP** pokazuje na górze listę wydań: **Obiekt**, **Karta**, **Data wydania**,
   **Stan** („czeka na WBPP", „do wciągnięcia N", „wciągnięte N", „do przeglądu N"). Najnowsze wydanie
   z czymś do wciągnięcia jest już zaznaczone, a pole **Wyjście WBPP:** wskazuje jego `out`.
3. Przeczytaj tabelę: **Plik**, **Rodzaj**, **Stan**, **Nazwa docelowa**, **Katalog docelowy**,
   **Wydanie**, **Powód**. Linia **Archiwum:** mówi, dokąd pójdą kopie (zmienisz ją przyciskiem
   **Zmień…**) - zajrzenie do innego archiwum nie blokuje powrotu; archiwum zamyka się dopiero po
   pierwszej kopii wciągniętej w tym oknie. Gdy archiwum okna różni się od archiwum bazy, pod linią
   stoi ostrzeżenie i przycisk **Wróć do archiwum bazy**.
4. Kliknij **Wciągnij N plików**.
5. Kliknij **Zamknij i przyjmij do archiwum**.

| Co WBPP oddał | Dokąd trafia | Kiedy |
|---|---|---|
| master flat | `CALIBRATION\masters\flats\<zestaw>\<filtr>` | gdy historia w pliku wymienia surowe flaty znane bazie |
| stos (`masterLight…`) | `STACKS\<obiekt>\<zestaw>\<filtr>` | gdy powstał z wydania Horreum |
| master dark, master bias | nigdzie - **do przeglądu** | archiwum nie ma surowych darków, z których mógłby powstać |

**Co program zrobi sam:** nada nazwę z faktów (obiekt, zestaw, filtr, noc), skopiuje plik bez
nadpisywania czegokolwiek, sprawdzi bajty kopii, a po **Zamknij i przyjmij do archiwum** przyjmie
kopie do bazy i zapisze dokładny rodowód stosów. Plik w `out` zostaje nietknięty.

> ⚠ **Zamknij i przyjmij do archiwum, nie samo Zamknij.** Zwykłe **Zamknij** zostawia kopie
> w archiwum, ale bez przyjęcia; stos dostaje wtedy tylko przybliżony rodowód. Gdy tak się stało,
> otwórz okno jeszcze raz - wiersz wydania powie „rodowód do zapisania", a przycisk przyjęcia będzie
> czekał. **Folderu wydania nie kasuj, dopóki lista tego mówi.**

Wiersz wydania, w którym nie ma już nic do wciągnięcia, mówi: „Folder wydania możesz skasować -
Horreum go już nie potrzebuje". Przycisk **Otwórz** pokaże go w Eksploratorze. Program sam niczego
nie kasuje - własne pliki obróbki przenieś przed skasowaniem.

Pozycja **do przeglądu** zawsze ma powód w kolumnie **Powód** (np. „brak historii integracji
w pliku", „stos spoza wydania Horreum"). Taki plik możesz skopiować ręcznie do `STACKS` archiwum -
**Przyjmij nowe** go weźmie.

---

## Popraw - dokończ to, czego automat nie był pewny

**Po co:** automat rozpoznaje większość klatek sam. Resztę rozstrzygasz Ty - i tylko tu.

Kafel **Popraw** prowadzi do **Porządki**: listy zadań ze stanu bazy. Każde ma liczbę i strzałkę `›`.
Pogrubiona liczba to robota; szare wiersze to historia albo stan bez roboty.

| Zadanie | Co znaczy | Dokąd prowadzi |
|---|---|---|
| **Klatki bez obiektu** | automat nie wie, co jest na zdjęciu | **Przegląd obiektów** |
| **Rodowód do potwierdzenia** | gotowy obraz nie wie, z czego powstał | perspektywa o tej nazwie, gesty w panelu **Rodowód** |
| **Rodowód z klatkami nowszymi niż obraz** | Twój werdykt potwierdził klatkę zrobioną po zintegrowaniu obrazu - nie mogła do niego wejść | perspektywa o tej nazwie, w panelu **Rodowód** przycisk **Odrzuć nowsze niż obraz** (cofniesz go „Cofnij werdykt” na pasku) |
| **Klatki bez zestawu** | brak teleskopu × kamery (typowo RAW z lustrzanki) | **Przegląd obiektów**, gest **Przypisz zestaw…** |
| **Ogniskowa niezgodna z teleskopem** | ogniskowa w pliku odbiega od teleskopu o ponad 5 % | **Przegląd obiektów**, gest **Przypisz zestaw…** |
| **f/ niezgodna z teleskopem** | f/ w pliku odbiega od teleskopu o ponad 5 % (np. f/200 zamiast f/8) | perspektywa o tej nazwie, prawy klik **Popraw f/ w plikach (zgodnie z teleskopem)…** |
| **Teleskopy bez etykiety** | sprzęt ma tylko techniczną nazwę z nagłówka | **Oś teleskopu** |
| **Klatki bez stanowiska** | nagłówek nie niesie GPS | **Oś obserwatorium**, gest **Wskaż stanowisko…** |
| **Stanowiska bez nazwy** | miejsce ma tylko współrzędne | **Oś obserwatorium** |
| **Duplikaty (>1 kopia)** | ta sama klatka leży w kilku miejscach | perspektywa **Duplikaty** |
| **Zniknięte z dysku** | żadnej kopii klatki nie ma już na dysku | perspektywa **Zniknięte** |
| **Plik nie zgadza się z obiektem** | plik leży w folderze innego obiektu albo jego karta `OBJECT` mówi co innego niż baza | perspektywa o tej nazwie, gest **Uzgodnij pliki…** |
| **Przerwane zmiany obiektu** | **Zmień obiekt…** albo **Uzgodnij pliki…** nie doszło do końca | okno przerwanego przebiegu z **Dokończ** i **Cofnij** |

Z podstrony wracasz strzałką **← Porządki**.

### Nazwij teleskop i stanowisko

1. **Teleskopy bez etykiety ›** otwiera **Oś teleskopu**. Na liście **Aktywne teleskopy (kanoniczne)**
   dwuklik w kolumnę **Etykieta**, wpisz swoją nazwę (np. `Newton 8"`), Enter.
2. Ten sam teleskop pod dwiema technicznymi nazwami: zaznacz wiersz, w **Scal zaznaczony w:** wybierz
   drugi, kliknij **Scal**. Pomyłkę cofnie **Cofnij scalenie**.
3. **Stanowiska bez nazwy ›** działa tak samo (**Oś obserwatorium**, kolumna **Nazwa**). Dwa zapisy
   tego samego miejsca łączysz **Scal**.
4. Klatki bez GPS: na **Oś obserwatorium** kliknij **Wskaż stanowisko…** - okno grupuje je po folderach.

> Nazwy i scalenia są **odwracalne**, dlatego program nie pyta „czy na pewno?".

### Popraw ogniskową i f/ teleskopu

Teleskop w Horreum to konkretny teleskop z konkretną ogniskową. Kolumny **f/** i **Ogniskowa** na
**Oś teleskopu** pokazują wartość z plików - tę, którą zapisuje większość klatek tego teleskopu.
Liczy się ona od nowa po każdym **Przyjmij** i po każdym przypięciu klatek do teleskopu.

1. Pliki mają błąd albo chcesz potwierdzić wartość: dwuklik w **f/** albo **Ogniskowa**, wpisz liczbę,
   Enter - także tę samą, którą widzisz. Twoja wartość ma znacznik `↺` i wygrywa w osi, w planerze
   i w Porządkach. Pliki zostają bez zmian. Podpowiedź komórki dalej mówi, co zapisują pliki, np.
   „pliki: 784 mm (7370 kl.)". Szara komórka z podpowiedzią „Nieaktualne” przeliczy się przy
   najbliższym **Przyjmij**.
2. Pusty wpis albo **Przywróć z plików** (blok **Optyka** pod listą scalonych) zdejmuje Twoją
   wartość. Podpowiedź przycisku mówi przed kliknięciem, co zostanie w polu.
3. Panel **Zestawy** pokazuje, co teleskop daje z każdą kamerą: piksel, skalę w ″/px (także przy
   bin 2) i kadr. Średnica wyliczona z ogniskowej i f/ stoi nad nim, w bloku **Optyka**.

Horreum nigdy nie zakłada teleskopu sam. Klatki, których ogniskowa odbiega od teleskopu o ponad 5 %,
czekają w zadaniu **Ogniskowa niezgodna z teleskopem**. **Przypisz zestaw…** pokazuje wtedy tylko
teleskopy o pasującej ogniskowej. Gdy żaden nie pasuje, wybierz **Dopisz nowy…** i podaj nazwę,
ogniskową, f/ i park. Pole parku startuje od parku teleskopu, w którym klatki są dziś. Twój wybór
zostaje na stałe - kolejne **Przyjmij** go nie zmieni. Pomyłkę z **Dopisz nowy…** naprawiasz,
scalając nowy teleskop na **Oś teleskopu** z właściwym.

**f/ niezgodna z teleskopem** pokazuje klatki z kolumną FOCRATIO. Zaznacz je, prawy klik
**Popraw f/ w plikach (zgodnie z teleskopem)…** - wpisy trafiają do szuflady zapisu, a pliki zmieniają
się dopiero po **Zapisz**. Gest poprawia tylko mniejszość. Gdy f/ teleskopu nie zgadza się
z większością jego plików, gest odmawia i każe sprawdzić Oś teleskopu.

### Nazwij obiekty, których automat nie rozpoznał

**Klatki bez obiektu ›** otwiera **Przegląd obiektów**: z lewej **Biblioteka (obiekty)**, pod nią
**Kolejka przeglądu**. Klik w wiersz kolejki pokazuje po prawej jego klatki.

**Kolejka to kilka kubełków, bo drogi naprawy są różne:**

| Wiersz kolejki | Co znaczy | Czym naprawiasz |
|---|---|---|
| nazwa z nagłówka, np. `FlatWizard · 12 klatek` | plik ma nazwę, program jej nie zna | **Przypisz obiekt…** |
| **bez nazwy w nagłówku** | plik nic nie mówi o obiekcie | **Napraw nagłówek…** - nazwa idzie do pliku |
| **bez nazwy, format bez karty (RAW)** | zdjęcie z lustrzanki, format nie ma gdzie zapisać nazwy | **Przypisz obiekt…** - nazwa idzie do bazy |
| **bez nazwy, gotowe stosy** | obraz po integracji bez nazwy | **Napraw nagłówek…** albo propozycja z folderu niżej |
| **…z tego ze ścieżki** | folder podpowiada nazwę, program czeka na Twoje „tak" | **Zatwierdź ze ścieżki…** |
| dopisek **cofnięte ręką** | sam zdjąłeś tu nazwę - to decyzja, nie brak wiedzy | program uprzedzi, że nadpisze Twój werdykt |

**Wygaszony przycisk tłumaczy się sam** - najedź na niego myszą, a powie, czego brakuje albo która
droga jest właściwa dla zaznaczonego wiersza.

#### Przypisz obiekt…

1. Kliknij wiersz kolejki - po prawej jego klatki, **wszystkie zaznaczone**. Możesz przyciąć
   zaznaczenie (`Ctrl`, `Shift`).
2. Kliknij **Przypisz obiekt…**.

| Pole | Co zrobić |
|---|---|
| **Istniejący obiekt:** | rozwiń listę i wskaż obiekt z biblioteki |
| albo nowa nazwa | wpisz nazwę, jak ją znasz: `IC 1795`, `LMC`, `Księżyc`, `C/2023 A3` - wypełnione pole wygrywa z listą |

3. Zatwierdź przyciskiem **Przypisz N klatek**.

Nowa nazwa zostaje zapamiętana jako **alias**: kolejne klatki z takim zapisem w nagłówku program
rozpozna sam. Nazwa spoza katalogów (`LMC`, `Księżyc`) staje się **obiektem własnym**. Po zapisie
dostajesz zdanie z rozbiciem: ile klatek zmieniono i **dlaczego resztę pominięto** (kalibracja, klatki
z nazwą w nagłówku, klatki zmienione w międzyczasie).

#### Zatwierdź ze ścieżki…

Gdy trzymasz zdjęcia w folderach nazwanych obiektami (`…\NGC6960\…`), program to widzi i
**proponuje**, ale nigdy nie zapisuje sam - folder bywa śmietnikiem. Zaznacz wiersz **…z tego ze
ścieżki** i kliknij **Zatwierdź ze ścieżki…**. Okno pokazuje propozycje pogrupowane po nazwie, z liczbą
klatek. Odznacz to, czego nie chcesz, i kliknij **Zatwierdź zaznaczone**. Tam, gdzie plik na to
pozwala, nazwa trafia także do pliku jako karta `OBJECT`; te karty cofniesz przyciskiem
**Cofnij karty** do zamknięcia okna.

> **Nagłówek jest ważniejszy niż folder.** Gdy plik sam mówi, co przedstawia, program wierzy jemu.

#### Napraw nagłówek…

**Napraw nagłówek…** dopisuje plikom kartę `OBJECT`, żeby nazwa została w archiwum na zawsze, także
dla innych programów.

> ⚠ **To zapis na dysku.** Okno najpierw pokazuje listę plików pogrupowaną po folderach i dokładną
> nazwę, która do nich pójdzie („do pliku: OBJECT = NGC7000") - przeczytaj ją przed **Zapisz karty**.
> Każdy zapis ma kopię zapasową nagłówka, więc istnieje **Cofnij**. Same dane obrazu zostają nietknięte.

Po zapisie kliknij **Rozwiąż teraz** - obiekt w bazie wypełni się z nowej karty.

### Poprawki na zaznaczeniu (Znajdź i Zbiory klasyczne)

Nie musisz iść przez kolejkę. Zaznacz klatki w **Znajdź** i użyj menu **Obiekt**:

- **Przypisz obiekt…** - to samo okno co wyżej,
- **→ NAZWA** - skrót do nazw użytych ostatnio, przypisuje od razu, bez okna,
- **Cofnij przypisanie** - zdejmuje nazwę postawioną ręką albo przez folder,
- **Przywróć cofnięte przypisanie** - odwraca to zdjęcie,
- **Zmień obiekt…** - zmienia obiekt razem z plikiem (opis niżej).

> **Cofnięcie nie kasuje faktów z plików.** Nazwa odczytana z nagłówka albo z pozycji na niebie
> zostaje. Cofnięcie zostaje też cofnięciem: klatka nie dostanie nazwy z powrotem przy kolejnym
> przyjęciu, tylko poczeka w kolejce na Twoją decyzję.

#### Zmień obiekt… - obiekt, folder i karta razem

**Przypisz obiekt…** zmienia tylko bazę. **Zmień obiekt…** robi trzy rzeczy naraz: przepina obiekt
w bazie, przenosi plik do folderu nowego obiektu w archiwum i wpisuje do pliku kartę `OBJECT`.
Każdy plik przechodzi całość albo nic - nie zostaje plik w nowym folderze ze starą kartą.

1. Zaznacz klatki, w menu **Obiekt** kliknij **Zmień obiekt…** i wybierz nowy obiekt.
   Sam wybór niczego nie zapisuje.
2. Okno **Zmień obiekt** pokazuje plan: ścieżkę dziś i po zmianie, kartę przed i po, katalogi do
   założenia i puste katalogi do usunięcia. Klatki, których gest nie ruszy, stoją osobno z powodem.
3. Kliknij **Zmień obiekt (N)**. Wynik mówi, ile plików przeszło do folderu obiektu.

W nazwie pliku zmienia się tylko człon obiektu na początku, reszta zostaje znak w znak. Nazwa, która
obiektem się nie zaczyna (np. nazwa z aparatu), zostaje cała.

**Cofnij** w tym samym oknie przywraca karty, pliki, katalogi i obiekt. Po zamknięciu okna cofnięcie
robi wiersz poleceń: `horreum object-change undo` z numerem przebiegu.

**Uzgodnij pliki…** to ten sam gest bez zmiany obiektu: obiekt w bazie zostaje, plik dogania go
folderem i kartą. Klatki do uzgodnienia zbiera wiersz Porządków **Plik nie zgadza się z obiektem** -
zaznacz je w perspektywie i prawym klikiem wybierz **Uzgodnij pliki…**.

> **Plik zajęty przez inny program.** Gdy plik trzyma podgląd, Eksplorator albo antywirus, Horreum
> chwilę czeka i próbuje ponownie. Jeśli plik dalej jest zajęty, ta jedna pozycja kończy się
> powodem „plik zajęty przez inny program” i zostaje nietknięta, a reszta przebiegu idzie dalej.
> Zamknij program, który trzyma plik, i powtórz gest na tej klatce (nowy podgląd).

W **Zbiory klasyczne** obok stoi menu **Klatka**: **Wycofaj klatkę…** (klatka, której wszystkie kopie
zniknęły z dysku, schodzi z oczu) i **Przywróć klatkę**.

**Popraw nagłówki…** otwiera panel, który liczy i wpisuje wartości kart nagłówka na wielu plikach
naraz (pola **Oblicz:** i **Przypisz:**). Zmiany nie idą od razu na dysk - czekają w **Poczekalnia
zmian**. Tam je przeglądasz i klikasz **Zatwierdź** albo **Odrzuć**; zapisane cofa **Cofnij**.

### Ostatni gest i droga powrotu

Każdy gest ręki zostawia na pasku stanu i w wierszu **Ostatnio** na Domu przycisk drogi powrotu
(np. **Cofnij uwagi**). Napis przycisku mówi, co zrobi klik - bywa, że pierwszy klik pokazuje cel
gestu, a dopiero następny go cofa.

---

## Więcej…

Przycisk **Więcej…** na Domu zbiera narzędzia rzadsze niż cztery kafle:

| Pozycja | Co otwiera |
|---|---|
| **Wciągnij z WBPP…** | okno **Wciągnij wyniki WBPP** - to samo, co przycisk w sekcji **Stosy** strony **Dostawa** |
| **Planer** | co da się dziś sfotografować i ile materiału już masz |
| **Mapa stanowisk** | **Oś obserwatorium**: tabela stanowisk z mapą; **Otwórz w OpenStreetMap…** pokaże miejsce w przeglądarce |
| **Nazwy plików…** | **Zbiory klasyczne** z panelem **Uporządkuj nazwy plików…** |
| **Makra nagłówków…** | **Zbiory klasyczne** z panelem **Popraw nagłówki…** |
| **Perspektywy** | **Zbiory klasyczne** z listą perspektyw |
| **Tryb zaawansowany dostawy** | stronę **Dostawa** bez uruchamiania przyjęcia |
| **Zbiory klasyczne** | pełny widok wszystkich klatek z filtrami |

### Planer - co sfotografować

**Planer** patrzy w przód: bierze Twoje stanowisko, sprzęt i dzisiejszą datę i mówi, co da się dziś
złapać oraz ile materiału na to już masz. Każdy wiersz to jeden cel:

| Kolumna | Co mówi |
|---|---|
| **Cel** / **Typ** | co to za obiekt (mgławica, galaktyka…) |
| **Rozmiar** / **Zestaw i kadr** / **Wypełn.** | czy zmieści się w kadrze Twojego sprzętu |
| **Okno** / **Kulminacja** | kiedy dziś jest nad horyzontem i kiedy stoi najwyżej |
| **Pokrycie** | ile materiału już masz - liczone z Twojego archiwum |
| **Koszt B/D/W** | ile jeszcze trzeba, żeby domknąć |
| **Rada** | podpowiedź programu |
| **Plan** / **Notatka** | Twoja decyzja i Twój komentarz |

**Pokrycie liczy się z gotowych obrazów, nie z klatek na dysku.** Te same klatki w dwóch stosach nie
liczą się podwójnie.

> Kolumna **Plan** jest wyłącznie Twoja - program nigdy sam nie oznaczy celu jako zrobionego.

### Zbiory klasyczne

Ten sam katalog co w **Znajdź**, ale z pełnym zestawem kontrolek: filtry po lewej (**Obiekt**,
**Filtr**, **Rodzaj**, **Teleskop**, **Noc**, **Kanał**), lista **Perspektywa:** i **Grupuj wg:** nad
tabelą, panel **Pola (kolumny)** do dokładania kolumn z nagłówka. Wejdziesz tu z **Więcej…** albo
przyciskiem **Zbiory klasyczne** w pasku Znajdź - zbiór zostaje ten sam.

Gotowe **perspektywy**: **Przegląd** (wszystko), **Kalibracja**, **Duplikaty**, **Zniknięte**,
**Rodowód do potwierdzenia**, **Do przeglądu** i kilka list historii (**Zastąpione**, **Wycofane**,
**Brakujące kopie**). Własny układ zapiszesz przyciskiem **★ Zapisz widok** - zapisane widoki siedzą
w bazie, więc jadą z nią na inny komputer. **× Wyczyść zbiór** zdejmuje wszystkie filtry jednym klikiem.

Pasek zbioru ma tu dwie akcje, które **ruszają pliki na dysku**:

- **Uporządkuj nazwy plików…** - zmienia nazwy plików według faktów z nagłówka,
- **Wydaj na stół…** - wydaje bieżącą perspektywę (zamiast jednego obiektu) jako drzewo linków;
  cel musi leżeć pod `_WBPP` albo `_Review`.

Obie najpierw pokazują **podgląd** i nie robią nic, dopóki go nie zatwierdzisz. Zmiany nazw czekają
w **Poczekalnia zmian** i mają **Cofnij**.

### Tryb zaawansowany dostawy

Na stronie **Dostawa**, pod złotą akcją, możesz wskazać **inny** katalog niż zapamiętany
(**Wskaż katalog…**) i puszczać etapy pojedynczo: **Skanuj**, **Grupuj**, **Rozwiąż**, **Kalibracja**,
**Rodowód kalibracji**, **Policz rodowód stosów**, **Pokaż deltę**. **Sprawdź obecność** porówna
katalog z bazą i powie, czego nie ma na dysku - zapis „zniknęło" robi dopiero **Oznacz zniknięte**.
Na co dzień wystarcza **Przyjmij nowe**.

### Menu

- **Plik**: **Otwórz bazę…**, **Nowa baza…**, **Folder roboczy WBPP…**.
- **Widok**: motyw **Ciemny** / **Jasny** i język (**Polski** / **English** - zadziała po ponownym
  uruchomieniu).

---

## Przykład od początku do końca

Archiwum `R:\ASTRO_` ma 4 000 plików FITS z dwóch sezonów, robionych dwoma teleskopami.

1. **Plik → Nowa baza…** → `R:\ASTRO_\katalog.db`. **Plik → Folder roboczy WBPP…** → `R:\ASTRO_`.
2. **Dom → Przyjmij** → wskazujesz `R:\ASTRO_` → czekasz kilka minut. Raport: „4000 nowych klatek",
   **Nie rozpoznałem: 140 klatek**.
3. W raporcie stoi „„Ameryka” ×40 w tej dostawie" → **Przypisz obiekt…** → `NGC 7000`. Pasek:
   „Zapamiętałem: „Ameryka” = NGC7000".
4. Kafel pokazuje **Popraw · 3**. W **Porządki**: Teleskopy bez etykiety 2, Stanowiska bez nazwy 1.
   Nazywasz teleskopy `Newton 8"` i `Refraktor 80/480`, stanowisko `Taras`.
5. Zostaje **Klatki bez obiektu**: w kolejce `FlatWizard · 68` (to narzędzie, nie obiekt - zostawiasz)
   oraz **…z tego ze ścieżki** z trzema nazwami. **Zatwierdź ze ścieżki…**, odznaczasz jedną
   wątpliwą, zatwierdzasz resztę.
6. **Dom → Znajdź** → `NGC 7000 filtr:Ha` → widzisz 200 klatek z trzech nocy. Zaznaczasz te z nocy
   z chmurami → **Uwagi…** → „chmury po 2:00".
7. **Dom → Wydaj do WBPP** → NGC7000 (kropka bursztynowa: flat 80 % + surowe 20 %) → **Dalej** →
   karta **Folder roboczy** → podgląd → **Utwórz N linków** → **Kopiuj ścieżkę**.
8. W WBPP: **Add Directory** na `R:\ASTRO_\_WBPP\OBJECTS\NGC7000`, **Output Directory** = skopiowana
   ścieżka `out`. Obróbka.
9. **Dostawa → Wciągnij z WBPP…** → wydanie NGC7000 „do wciągnięcia 3" (dwa mastery flat, jeden stos)
   → **Wciągnij 3 plików** → **Zamknij i przyjmij do archiwum**. Na liście: „Folder wydania możesz
   skasować".

Miesiąc później dogrywasz nową noc do `R:\ASTRO_`. **Dom → Przyjmij** przechodzi w kilkanaście sekund,
bo znane pliki są pomijane, a „Ameryka” w nagłówku rozpoznaje się już sama.

---

## Co robi się samo, a czego program nie zrobi

**Robi samo:**

- czyta nagłówki i buduje katalog (przyjmowanie tylko odczytuje pliki),
- ustala teleskopy, zestawy i stanowiska, rozpoznaje obiekty (katalogi, nazwy potoczne, pozycja na
  niebie) i filtry,
- dobiera do lightów mastery kalibracyjne, a w wydaniu - surowe flaty, gdy mastera brak,
- wiąże gotowy obraz z klatkami, z których powstał,
- przy kolejnych przyjęciach pomija pliki, które już zna,
- zapamiętuje nazwę przypisaną ręką i rozpoznaje ją w następnych dostawach,
- pamięta ostatnią bazę, ostatni katalog dostawy, folder roboczy, cele wydania i motyw.

**Nie zrobi bez Twojej wyraźnej decyzji:**

- **nie zmienia, nie przenosi i nie kasuje plików archiwum** przy przyjmowaniu,
- **nie wymyśla nazw** teleskopów i stanowisk,
- **nie zgaduje na siłę** obiektu - niepewne klatki czekają w kolejce przeglądu,
- **nie ufa folderowi bez pytania** - nazwa z folderu to propozycja do potwierdzenia,
- **nie odwraca Twojego cofnięcia** - zdjęta nazwa nie wróci sama,
- **nie wpisuje uwag do plików** - uwaga żyje wyłącznie w bazie,
- **nie wciąga wyników WBPP sam** - robisz to w oknie **Wciągnij wyniki WBPP**,
- **nie buduje masterów dark** - archiwum nie ma surowych darków, więc w wydaniu darki są wyłącznie
  gotowymi masterami,
- **nie kasuje folderu wydania** ani niczego w folderze roboczym - mówi tylko, kiedy możesz to zrobić,
- **nie oznacza celu jako zrobionego** w Planerze,
- operacje zapisu na dysk (karta `OBJECT`, **Popraw nagłówki…**, **Uporządkuj nazwy plików…**,
  wydanie, wciąganie) to **osobne, jawne akcje** - zawsze najpierw pokazują podgląd.

---

## Checklista pierwszego uruchomienia

- ☐ Program się otwiera, widać ekran **Dom** i pasek boczny
- ☐ Założona baza; **Co mam:** pokazuje liczby po pierwszym przyjęciu
- ☐ **Przyjmij** doszło do końca, panel **Co przyszło** pokazuje dostawę
- ☐ **Znajdź**: nazwa Twojego obiektu pokazuje jego klatki
- ☐ **Plik → Folder roboczy WBPP…** wskazany; pasek stanu potwierdził „Folder roboczy: …"
- ☐ W **Porządki** teleskopy mają etykiety, stanowiska nazwy (kafel **Popraw** bez liczby albo z tym,
  co świadomie zostawiasz)
- ☐ **Klatki bez obiektu** są puste **albo** wiesz, co w nich zostawiasz

---

## Ściąga - „chcę… → robię…"

| Chcę… | Robię… |
|---|---|
| Założyć katalog | **Plik → Nowa baza…** |
| Wrócić do swojego katalogu | **Plik → Otwórz bazę…** (albo sam wróci przy starcie) |
| Ustawić stół do obróbki | **Plik → Folder roboczy WBPP…** |
| Wczytać nowe zdjęcia | **Dom → Przyjmij** |
| Wskazać inny katalog niż zwykle | **Więcej… → Tryb zaawansowany dostawy → Wskaż katalog…** |
| Dodać gotowe obrazy z drzewa obróbki | **Dostawa → Wciągnij stosy…** |
| Znaleźć obiekt po nazwie potocznej | **Dom → Znajdź**, wpisz nazwę, Enter |
| Zobaczyć jedną noc albo filtr | **Znajdź**: `noc:2026-08-08`, `filtr:Ha` |
| Dopisać uwagę do klatek | **Znajdź → zaznacz → Uwagi…** |
| Znaleźć klatki po uwadze | **Znajdź**: słowo z uwagi albo `uwagi:chmury` |
| Przygotować obiekt do WBPP | **Dom → Wydaj do WBPP → obiekt → Dalej → Utwórz N linków** |
| Wziąć ścieżkę wyjścia dla WBPP | okno wydania → **Kopiuj ścieżkę** |
| Przenieść mastery i stosy z WBPP do archiwum | **Więcej… → Wciągnij z WBPP… → Wciągnij N plików → Zamknij i przyjmij do archiwum** |
| Zobaczyć, co czeka na mnie | **Dom → Popraw** |
| Nazwać teleskop | **Porządki → Teleskopy bez etykiety → dwuklik w Etykieta** |
| Nazwać miejsce | **Porządki → Stanowiska bez nazwy → dwuklik w Nazwa** |
| Nazwać klatki, których automat nie rozpoznał | **Porządki → Klatki bez obiektu → wiersz kolejki → Przypisz obiekt…** |
| Przyjąć nazwy podpowiedziane przez foldery | **Porządki → Klatki bez obiektu → …z tego ze ścieżki → Zatwierdź ze ścieżki…** |
| Wpisać nazwę na stałe do pliku | **Porządki → Klatki bez obiektu → bez nazwy w nagłówku → Napraw nagłówek…** |
| Nazwać klatki, które właśnie widzę | **Znajdź → zaznacz → Obiekt → Przypisz obiekt…** |
| Cofnąć własną pomyłkę w nazwie | **Znajdź → zaznacz → Obiekt → Cofnij przypisanie** |
| Zobaczyć, z czego powstał gotowy obraz | **Znajdź → zaznacz obraz → Rodowód…** |
| Cofnąć ostatni gest | przycisk w wierszu **Ostatnio** na Domu albo na pasku stanu |
| Sprawdzić, co sfotografować dziś | **Więcej… → Planer** |
| Znaleźć duplikaty | **Porządki → Duplikaty (>1 kopia)** |
| Zmienić motyw | **Widok → Jasny** / **Ciemny** |
| Sprawdzić, którą mam wersję | tytuł okna |

## FAQ

**Przyjmowanie coś zmieni w moich plikach?** Nie. Czyta wyłącznie nagłówki. Zapis na dysk to osobne,
jawne akcje z podglądem.

**Przyjąłem dwa razy ten sam folder - mam duplikaty?** Nie. Horreum rozpoznaje pliki po zawartości
i pomija znane. Duplikat powstaje tylko z realnie drugiej kopii pliku.

**Przeniosłem pliki na inny dysk - stracę historię?** Nie. Tożsamością jest zawartość, nie ścieżka.

**Nie widzę żadnych klatek.** Sprawdź, czy baza jest otwarta i czy **Przyjmij** doszło do końca.
W **Znajdź** zdejmij chipy (×) albo w **Zbiory klasyczne** kliknij **× Wyczyść zbiór**.

**Część klatek nie ma obiektu.** To normalne dla nietypowych nazw w nagłówku. Czekają w **Porządki →
Klatki bez obiektu** albo od razu w raporcie **Co przyszło**, z przyciskiem **Przypisz obiekt…**.

**Nadałem złą nazwę - da się to odkręcić?** Tak: **Znajdź → zaznacz → Obiekt → Cofnij przypisanie**.
Nazwa odczytana z pliku zostaje, bo to fakt z archiwum, nie Twoja pomyłka.

**Zdjąłem nazwę, a po przyjęciu wróciła.** Cofnięcie jest trwałe. Jeśli nazwa wróciła, pochodzi
z nagłówka pliku - zmień ją w pliku przez **Napraw nagłówek…**.

**Nazwałem cały kubełek, a program mówi „przypisano 5 z 8".** Zdanie pod spodem wylicza, czemu
pominął resztę: kalibracja (nie ma obiektu z definicji), klatki z nazwą w nagłówku albo klatki
zmienione w międzyczasie.

**Czy „Napraw nagłówek…" zepsuje mi zdjęcie?** Nie - dopisuje wyłącznie kartę `OBJECT`, dane obrazu
zostają. Przed zapisem widzisz listę plików i nazwę, a po zapisie działa **Cofnij**.

**Wydanie zajmie mi drugi raz tyle miejsca na dysku?** Nie, jeśli folder roboczy leży na tym samym
dysku co archiwum - wydanie to linki. Podgląd mówi to wprost: „ten sam wolumen → hardlink (zero
bajtów)" albo „inny wolumen → kopia bajtów".

**Mogę skasować folder `_WBPP\OBJECTS\…`?** Tak, gdy okno **Wciągnij wyniki WBPP** mówi „Folder
wydania możesz skasować". Wcześniej mogą tam czekać wyniki WBPP albo dokładny rodowód stosów.

**WBPP zrobił master dark - czemu Horreum go nie wciąga?** Archiwum nie ma surowych darków, więc
nie da się dowieść, z czego ten master powstał. Trafia do przeglądu z powodem.

**Skąd Planer wie, ile już mam?** Liczy godziny z Twojego archiwum - z gotowych obrazów i klatek,
które do nich weszły.

**Gdzie się podziały strony Dostawa, Porządki i Zbiory?** Są dalej - w pasku bocznym pod napisem
**Więcej** i pod przyciskiem **Więcej…** na Domu. Cztery kafle prowadzą do tych samych miejsc
krótszą drogą.

<!-- APPENDIX-START: sekcja techniczna - usuwana z wersji PDF dla czytelnika -->

## Dla nas - mapowanie na system

> Ta sekcja jest dla utrzymujących projekt, nie dla użytkownika końcowego. Odcinana przy generowaniu PDF.

**Nawigacja** (`horreum/gui/app.py`): wiersze sidebara `NAV_DOM`, `NAV_ZNAJDZ`, `NAV_WIECEJ`
(nagłówek sekcji bez flag), `NAV_DOSTAWA`, `NAV_ZBIORY`, `NAV_PORZADKI`, `NAV_PLANER`; strony stosu
`STRONA_DOM`, `STRONA_ZBIORY`, `STRONA_DOSTAWA`, `STRONA_PORZADKI`, `STRONA_PLANER`. Dom jest stroną
startu po otwarciu bazy. Menu: `menu.file` (`menu.open_db`, `menu.new_db`, `menu.work_root`),
`menu.view` (motyw + język, restart).

**Dom** = `HomeView` (`horreum/gui/home.py`). Sygnały zamiarów, trasy w `MainWindow`: `przyjmij` →
`_on_przyjmij` (Dostawa + `PipelineView.receive`), `znajdz` → `show_find`, `wydaj` →
`_open_object_release` gridu, `popraw` → `NAV_PORZADKI`, `teczka` → `_on_teczka_domu`
(`apply_object_facet`), `wiecej(klucz)` → `_on_wiecej_domu` (`WIECEJ_PLANER`, `WIECEJ_STANOWISKA`,
`WIECEJ_NAZWY`, `WIECEJ_MAKRA`, `WIECEJ_PERSPEKTYWY`, `WIECEJ_DOSTAWA`, `WIECEJ_KLASYCZNE`).
„Co mam" = `queries.home_summary`, teczki = `queries.release_readiness` w `TeczkiWorker` (do 18 kart,
rzędy dopasowane do wysokości), „Ostatnio" = recepta ze strumienia Zbiorów albo
`queries.last_hand_gesture`. Licznik kafla Popraw = plakietka Porządków.

**Przyjmij** = `PrzyjmijView` (`horreum/gui/flows/przyjmij.py`) nad TYM SAMYM `PipelineView`.
Raport „Co przyszło" = `queries.delivery_report` od znacznika `since` przebiegu `all`; gest
„Przypisz obiekt…" przy nazwie = `repo.user_assign_object` (populacja `queries.object_review_frames`),
zdanie `intake.assign.remembered`. Łańcuch `all` (`pipeline._run_all`): skan → fakty kopii
(`derive.adopt_stages`) → grupuj → rozwiąż → kalibracja → rodowód → rodowód stosów → delta, plus
raport obecności. „Przyjmij nowe" = `all` na `pipeline/last_source` (QSettings). Skan przyrostowy,
tożsamość = `sha1_data`; `_WBPP`/`_Review` wykluczone (`scan.EXCLUDED_DIR_NAMES`).

**Znajdź** = `ZnajdzView` (`horreum/gui/flows/znajdz_view.py`) nad TYM SAMYM `FramesView` co Zbiory
klasyczne (prezentacja `PREZENTACJA_ZNAJDZ`). Parser Qt-wolny `horreum/gui/flows/znajdz.py`
(`parse` → `resolve` → `FindState`): prefiksy `noc/night`, `filtr/filter`, `teleskop/telescope`,
`zestaw/setup/rig`, `uwagi/notes`; fraza bez prefiksu = obiekty (dokładnie, potem szukajka listwy),
bez trafienia = uwagi. Kolumny prostego zestawu z `grid_model.py` (`find.col.*`). Pasek czasowników
`SelectionBar._rzad` w prezentacji Znajdź.

**Uwagi** (migracja 0032): okno `NoteDialog` (`horreum/gui/note_dialog.py`) zwraca
intencję, zapis `repo.set_frame_note` / `repo.clear_frame_note`, limit `repo.NOTE_MAX` = 300 po
`repo.normalize_note`. Nigdy do nagłówka. Wchodzą do `horreum human-facts --baseline`.

**Wydaj do WBPP**: `ObjectPickDialog` (`horreum/gui/projection_dialog.py`, read-model
`queries.release_readiness`, kropka `_STATE_ROLES`/`_STATE_TIPS`) → `ProjectionDialog(object_id=…)`
→ `projection.plan_object` (okno surowych flatów `lineage.RAW_FLAT_WINDOW_DAYS` = 30) →
`projection.object_root` = `<karta>/OBJECTS/<obiekt>`, układ `wbpp-obiekt`
(`<zestaw>/LIGHT|MASTER|FLAT_RAW/<filtr|relacja>`), wyjście `projection.OUTPUT_DIR` = `out`, manifest
`_PROJEKCJA.json` (`projection.object_manifest`). Hardlink vs kopia z seriali wolumenów. Folder roboczy:
QSettings `work/root`, `projection.work_wbpp_root` (dokłada `_WBPP`), karta „Folder roboczy” przez
`projection_dialog.remember_target`. Wydanie perspektywy („Wydaj na stół…”) = ten sam dialog
z `frame_ids`, układy `po-obiektach` / `wbpp-feed`.

**Wciągnij z WBPP… (żniwa)**: przycisk `pipeline.btn.harvest` w sekcji Stosy →
`PipelineView.open_harvest` albo pozycja `WIECEJ_ZNIWA` menu „Więcej…” Domu
(`MainWindow._on_wiecej_domu`) → `MainWindow._on_open_harvest` → `HarvestDialog`
(`horreum/gui/harvest_dialog.py`) nad rdzeniem `horreum/harvest.py` (plan bez mutacji; kopia
`projection.copy_master`; zeznanie `_ZNIWA_<ts>.json`). Master flat →
`CALIBRATION\masters\flats\<zestaw>\<filtr>` (świadek: nazwy wejść `ProcessingHistory` rozstrzygane bazą); stos →
`STACKS\<obiekt>\<zestaw>\<filtr>` (świadek: manifest wydania); master dark/bias → przegląd
(`no_raw_darks`). „Zamknij i przyjmij do archiwum” → `PipelineView.run_all_on` + po łańcuchu
`stacks.record_harvest_inputs` (rodowód dokładny); zwykłe „Zamknij” zostawia stosom rodowód okna czasu.

**Popraw** = Porządki (`horreum/gui/tasks.py`, `_TASKS`): wiersze akcyjne liczą się do plakietki,
`_BEZ_ROBOTY` (historia) wyszarzone. Podstrony: `_PAGE_TELESCOPE`, `_PAGE_OBSERVATORY`, `_PAGE_OBJECTS`.
Kolejka przeglądu obiektów (`queries.review_queue`): kubełki `object_review`, `nameless`,
`nameless_raw`, `nameless_stacks`, propozycje ścieżki, bez zestawu; partycja domyka się do
`review_frame_ids` (walidator `_partycja` w `tests/test_gui_queries_object.py`).

**Cztery drogi nadania obiektu**: ręka z kolejki (`repo.user_assign_object`) · ręka z zaznaczenia
(menu „Obiekt” paska `SelectionBar`, ten sam czasownik klingi) · potwierdzenie propozycji ścieżki
(`resolver.path_proposals`, źródło `path`, z kartą `OBJECT` tam, gdzie plik pozwala) · zapis karty
`OBJECT` do PLIKU (`RepairHeaderDialog` → `writeback`; gasi nagrobek `user_cleared`). Cofnięcie =
`repo.clear_object_assignment` (wyłącznie `CLEARABLE_OBJECT_SOURCES`: `path`, `user`); nagrobek
przeżywa `run_resolver`. Znaczniki kolumny „Obiekt” = `queries.object_cell`
(`CLEARED_MARK`, `RAW_MARK`, `HINT_MARK`).

**Perspektywy** (`PRESETS` gridu): Przegląd, Kalibracja, Duplikaty, Zniknięte, Rodowód do
potwierdzenia, Zastąpione, Wycofane, Wycofane, a plik wrócił, Brakujące kopie, Wersje stosów,
Klatki z niezgodnymi kopiami, Zeznanie z nieobecnej kopii, Nagłówek inny niż folder, Plik po
przerwanym zapisie, Zapis czeka na dokończenie, Do przeglądu; zapisane przez użytkownika mieszkają
w bazie (`saved_query`).

**CLI** (`horreum/cli.py`, dla zaawansowanych): `init`, `scan`, `stacks`, `group`, `resolve`,
`calibrate`, `lineage`, `stack-lineage`, `delta`, `rename` (DRY domyślnie, `--apply`/`--undo`),
`project` (drzewo pod WBPP, DRY domyślnie), `presence`, `human-facts`, `plan`, `target`,
`object-change finish|undo` (przebieg „Zmień obiekt…” po numerze ze zdania wyniku).

**Dystrybucja:** onefile - `dist\horreum-gui.exe` z `packaging\build.ps1 -Onefile`, publikowany jako
`Horreum-<wersja>-windows-x64.exe`. Numer wersji ma jednego właściciela (`pyproject.toml`), widać go
w tytule okna (bramka `tests/test_version.py`).

**Status dokumentu:** przepisany 2026-10-11 według czterech czasowników Domu, uzupełniony 2026-10-12
o **Zmień obiekt…** i **Uzgodnij pliki…**; opisuje wydanie 0.11.0 ze schematem bazy v36. Z poprzedniej wersji wypadły: wiersz Porządków
„XISF (nagłówki tylko do odczytu)” (zdjęty z `_TASKS`) oraz układ „Krok 1..6”. Nadal bez
opisu krok po kroku: panel **Popraw nagłówki…** (makra), **Uporządkuj nazwy plików…**, **Wydaj na
stół…**, panel **Rodowód…** w pełni (odniesienie czasu RAW, wybór innej nocy), Planer w pełni
(kuratela celów) i narzędzia kopii (**Ta kopia prowadzi**, **Wycofaj klatkę…** w szczegółach).

<!-- APPENDIX-END -->
