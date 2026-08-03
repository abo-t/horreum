# Historia zmian

Format wzorowany na [Keep a Changelog](https://keepachangelog.com/pl/1.1.0/).
Wersjonowanie [semantyczne](https://semver.org/lang/pl/). Projekt jest we wczesnym rozwoju —
schemat i API mogą się jeszcze zmieniać.

## [Niewydane]

### Dodane
- **Nazwę obiektu można teraz nadać i COFNĄĆ prosto z ekranu „Klatki".** Do tej pory nadanie nazwy
  ręką było jednokierunkowe: pomyłkę dawało się odwrócić tylko przez edycję pliku ze słownikiem,
  i tylko dla nazw, które w nim były. Pasek zaznaczenia dostał przycisk **„Obiekt ▾"** z dwiema
  pozycjami — „Nazwij zaznaczenie…" i „Cofnij przypisanie". Obie działają **wyłącznie na tym, co
  masz zaznaczone**, nigdy na całej widocznej liście; przy pustym zaznaczeniu są wygaszone.
  **Program chroni to, czego nie powinien ruszać, i mówi o tym wprost.** Cofnięcie zdejmuje tylko
  nazwy, które postawiła Twoja ręka albo folder — **nazwa odczytana z nagłówka pliku albo z pozycji
  na niebie zostaje**, bo to fakt z archiwum, a nie pomyłka do naprawienia. Nazywanie pomija
  kalibrację (dark, flat, bias — te obiektu nie mają z definicji), a cofanie pomija gotowe obrazy
  po integracji, bo odebranie im obiektu zerwałoby powiązanie ze zdjęciami, z których powstały.
  Po każdym geście dostajesz zdanie z rozbiciem: ile klatek zmieniono i **z jakiego powodu resztę
  pominięto** — osobno kalibrację, osobno klatki z nagłówka, osobno te, które zmieniły się
  w międzyczasie.
  **Cofnięcie zostaje cofnięciem.** Klatka, której zdjęto nazwę, nie dostanie jej z powrotem przy
  najbliższym „Rozwiąż" — nawet jeśli folder albo nagłówek dalej ją podpowiadają. Wraca do
  przeglądu i czeka na Twoją decyzję. Znak zapytania znika dopiero wtedy, gdy sam podasz nazwę
  ponownie albo wpiszesz ją do pliku przez „Napraw nagłówek…".
- **Klatki z lustrzanki można wreszcie nazwać ręką — kubełek „bez nazwy (RAW)" przestał być
  ślepym zaułkiem.** Wiersz w kolejce przeglądu mówił o nich od dawna, ale nie dało się w niego
  kliknąć: jedyna droga naprawy (ręczne przypisanie) była podpięta pod pozycje, które mają nazwę
  w nagłówku — a RAW jej nie ma z definicji formatu. Teraz wiersz otwiera listę tych klatek,
  a przycisk „Przypisz obiekt…" działa przy nim tak samo jak przy każdej innej pozycji.
  To jest droga awaryjna dla wszystkiego, czego nie domknie propozycja z folderu.
  **Nazywasz to, co masz zaznaczone.** Otwarcie kubełka zaznacza wszystkie jego klatki, więc
  „nazwij cały kubełek" to nadal jedno kliknięcie — ale możesz zaznaczenie przyciąć i nazwać
  tylko część. Ten kubełek nie jest jedną grupą, tylko resztą po wszystkich innych drogach:
  potrafi zebrać setki klatek z kilkudziesięciu różnych katalogów, a nazwy nadanej ręką dzisiejszy
  program jeszcze nie umie cofnąć. Przy pustym zaznaczeniu przycisk jest wygaszony.
- **Okno „Przypisz obiekt…" przyjmuje każdą nazwę, którą program naprawdę rozpozna.** Do tej pory
  żądało oznaczenia katalogowego, więc odrzucało `LMC`, `Moon` i nazwy potoczne — mimo że przebieg
  „Rozwiąż" rozwiązuje je bez wahania. Teraz okno pyta tej samej reguły co przebieg, a katalog
  i rodzaj obiektu bierze z tego, co ta reguła zwróci: nazwa spoza katalogów zostaje **obiektem
  własnym** (okno mówi o tym wprost, zanim klikniesz), a nie udawanym „deep sky" bez katalogu.
- **Klatki z lustrzanki dostają nazwę obiektu z FOLDERU — ale dopiero, gdy ją potwierdzisz.**
  Pliki RAW nie mają w sobie miejsca na nazwę obiektu (EXIF go nie zna), więc 763 zdjęcia
  z aparatu stały w kolejce przeglądu bez żadnej drogi wyjścia. Teraz Horreum czyta nazwę
  z katalogu, w którym leżą (`…\LIGHTS\LMC\…`), i **proponuje** ją — nie zapisuje. W kolejce
  przeglądu pojawia się wiersz „…z tego ze ścieżki", a pod nim okno z listą **pogrupowaną po
  nazwie**: 743 klatki to 36 pozycji do przejrzenia, nie 743. Przy każdej widzisz liczbę klatek,
  folder źródłowy i znacznik **„NOWA w bazie"** — bo to właśnie nowe nazwy warto obejrzeć, zanim
  wejdą do biblioteki (`NGC6960` obok istniejących `NGC6992` i `Veil` to ten sam obiekt nieba
  w trzech miejscach). Odznaczasz, czego nie chcesz, i zatwierdzasz resztę jednym kliknięciem.
  Sam przebieg „Rozwiąż" nie zmienia przy tym ani jednego wiersza — liczy tylko kandydatów
  i pisze o nich w raporcie Dostawy.
- **Katalog `_SOLAR` i `_COMETS` przestał być ślepym zaułkiem.** Zdjęcia Księżyca, Jowisza
  i komety 21P leżą o poziom głębiej niż zwykłe cele — program to teraz rozumie i nazywa je
  tak samo jak resztę.

### Zmienione
- **Okno „Napraw nagłówek…" i rozpoznawanie nazw mówią wreszcie JEDNYM głosem.** Do tej pory
  ekran i baza odpowiadały różnie na to samo pytanie: przebieg umiał nazwać `LMC` czy `Moon`,
  a okno naprawy przy tych samych plikach milczało. Teraz obie drogi pytają tej samej reguły,
  więc propozycja w oknie pojawia się wszędzie tam, gdzie program naprawdę rozpozna nazwę.
  Przy okazji zniknęła stara pułapka: folder ze sprzętem (`C8_2600MC`) nie udaje już oznaczenia
  katalogowego Caldwell 8.
- **Obiekty bez numeru katalogowego mają wreszcie własne miejsce — i Horreum je rozpoznaje.**
  Wielki Obłok Magellana, bańki Wolfa-Rayeta, cele o własnym imieniu: nazwy, których żaden katalog
  nie zna, bo nie mieszczą się w gramatyce `NGC`/`IC`/`Sh2`. Dotąd program mógł co najwyżej mieć je
  w spisie celów planera i nadal nie umiał nazwać ani jednej klatki. Teraz jest jeden plik takich
  obiektów, z którego korzystają OBIE strony: planer bierze z niego cele, a rozpoznawanie nazw —
  same nazwy. Wpisujesz „Large Magellanic Cloud" albo „LMC" w oknie „Napraw nagłówek…" i program
  je przyjmuje, zamiast odmawiać. Wpis może być **samą nazwą** — obiekt, którego nie da się
  zaplanować (LMC z Polski nigdy nie wschodzi), nie zaśmieca planu, ale w bibliotece istnieje.
  **Do tej klasy dołączył `Orion`** — szerokie pole gwiazdozbioru fotografowane obiektywem 50–70 mm,
  a więc coś zupełnie innego niż Wielka Mgławica w Orionie (`NGC1976`), która ma swój własny numer
  i swoje własne klatki. Nazwa opisuje to, co jest na zdjęciu: **cały gwiazdozbiór**. Kadry ciaśniej
  wycelowane w pas i miecz nie dostają osobnej nazwy — to nadal ten sam obszar nieba, a różni je
  obiektyw, nie obiekt.
- **Nazwy potoczne stają się równoważnościami, a ich wycofanie naprawdę się cofa.** Każda nazwa
  wpisana obok obiektu trafia do biblioteki jako jego druga nazwa, więc szukanie działa dla
  wszystkich naraz. Gdy usuniesz nazwę z pliku, program nie zostawia po niej kłamstwa: wycofuje
  równoważność **i odpina klatki**, które przez nią dostały obiekt — wracają do kolejki, zamiast
  zostać z nazwą, której już nie ma. Jeżeli nazwa jest już zajęta przez inny obiekt, program jej
  nie podmienia po cichu: melduje kolizję i zostawia decyzję Tobie.

- **Gotowe obrazy po integracji trafiają wreszcie do biblioteki — nową drogą „Stosy".** W Dostawie
  jest osobna sekcja: wskazujesz korzeń swojego drzewa obróbki, a Horreum wciąga z niego wyłącznie
  pliki `masterLight*.xisf` — bez wersji pochodnych (kadrowanych, po ABE, bez gwiazd). Korzeń jest
  zapamiętywany, więc następnym razem okno wyboru otwiera się od razu we właściwym miejscu.
  Droga jest w całości **tylko do odczytu**: ani jeden bajt w drzewie obróbki się nie zmienia.
  Świadomie stoi **osobno od „Przyjmij nowe"** — drzewo obróbki to nie archiwum, więc sięga się
  tam osobnym gestem, a codzienna dostawa zostaje bez zmian. Z wiersza poleceń: `horreum stacks`.
- **Gotowe obrazy bez nazwy obiektu mają w kolejce przeglądu własny wiersz** — i można je stąd
  naprawić tak samo jak klatki archiwum. Wiersz nie miesza się z klatkami z teleskopu, bo to inna
  populacja; ale wchodzi w niego kliknięciem, a okno „Napraw nagłówek…" dopisuje kartę `OBJECT`
  także do pliku po integracji.
- **Horreum wie, z czego powstał gotowy obraz.** Dla każdego wciągniętego stosu zapisuje jego
  rodowód — które klatki archiwum w nim siedzą — i mówi wprost, na jakiej podstawie: „plik sam
  to zeznał" (historia zapisana przez PixInsight) albo „wynika z czasu naświetlania" (kandydat).
  Gdy nagłówek obrazu opisuje jedną klatkę zamiast całej serii, program **nie zgaduje**: taki stos
  zostaje z jawnym powodem, zamiast dostać jedno przypadkowe zdjęcie i wyglądać wiarygodnie.
  Z wiersza poleceń: `horreum stack-lineage`.
- **Panel „Rodowód" odpowiada teraz na dwa pytania naraz.** Dla klatki z nieba mówi, czym ją
  skalibrowano (którym masterdarkiem, którym flatem i dlaczego akurat tym); dla gotowego obrazu —
  które klatki w nim siedzą. Jedna etykieta, dwie odpowiedzi zależne od tego, co zaznaczysz.
- **Plan celów mówi, ile godzin naprawdę weszło w gotowy obraz.** Obok „ile zebrałem" stoi teraz
  druga liczba — „w obrazach" — a pod kursorem, w kolumnie „Pokrycie", wypisuje się **gdzie te
  obrazy leżą**. Każda klatka liczy się **raz**, choć często siedzi w kilku obrazach naraz
  (ponowne złożenie tej samej nocy, wersja drizzle, wersja bez gwiazd): bez tego godziny rosłyby
  od samego przeliczania archiwum. Luki i rada nadal patrzą na godziny ZEBRANE — „jeszcze tego nie
  złożyłem" nie jest brakiem materiału i nie wyśle Cię po klatki, które już masz.
- **Perspektywy mieszkają w bazie i jadą razem z nią.** Nazwany widok („Do przeglądu Ha z A140R")
  był dotąd własnością komputera: nie przenosił się na laptopa i ginął przy przeinstalowaniu
  programu. Teraz siedzi w pliku biblioteki — skopiuj bazę, a perspektywy jadą z nią. Zapisanie
  pod nazwą, która już tam jest, **mówi wprost, że nadpisuje** (bo mogła przyjechać z drugiej
  maszyny z inną treścią). Perspektywy zapisane wcześniej program przenosi sam, przy pierwszym
  otwarciu Zbiorów.

### Naprawione
- **Rachunek „ile zapisano" przestał kłamać o cofniętych zapisach.** Kontrola spójności porównywała
  liczbę rzeczy w bazie z liczbą zapisanych zdarzeń, ale nie odejmowała tych, które wycofano —
  więc po każdym cofnięciu pokazywała rozjazd, który nie był błędem. Teraz odejmuje, a sama reguła
  jest wołana zarówno przez testy, jak i przez skrypt kontrolny — dotąd żaden test nie mógł jej
  sprawdzić, bo mieszkała wyłącznie w skrypcie.
- **Rozkład klatek nieba musi się domykać.** Program dzieli je na sześć rubryk (rozpoznane, bez
  nazwy, bez karty…) i nic nie sprawdzało, czy razem dają całość — a rozkład, który się nie domyka,
  wygląda na zielony właśnie wtedy, gdy coś wypadło. Doszła kontrola sumy.
- **Okno „Napraw nagłówek…" przyjmuje wreszcie Księżyc, planety i komety.** Sprawdzało nazwę
  węziej, niż potrafi ją potem rozpoznać sam program, więc odmawiało zapisania `Moon`, `Jupiter`
  czy `C/2023 A3` — mimo że po zapisie obiekt wskoczyłby na swoje miejsce. To samo dotyczyło
  nazwy, której nauczyłeś program wcześniej przez „Przypisz obiekt…". Nazwa, której nie zna nikt,
  nadal jest odrzucana — po to, żeby zapis do pliku nie zostawił klatki bez obiektu. (`WR134` był
  tu pierwotnie przykładem nazwy do nauczenia; w tym samym wydaniu trafił do pliku obiektów
  własnych, więc program zna go teraz od razu.)
- **Licznik na przycisku „Zapisz karty" mówi, ile ZOSTAŁO.** Po udanym zapisie przycisk zostawał
  wygaszony z liczbą sprzed zapisu, więc opisywał przeszłość. Teraz liczba znika, a po „Cofnij"
  wraca.
- **Oznaczenie celu, którego katalog już nie zna, daje się wreszcie zdjąć.** Po podmianie katalogu
  celów Twoja własna decyzja („zaplanowane", „zrobione") zostawała na liście z dopiskiem
  `[poza katalogiem]` — i nie było jak jej usunąć, bo program najpierw sprawdzał nazwę w katalogu
  i odmawiał. Teraz, gdy katalog nazwy nie rozstrzyga, zdejmowane jest oznaczenie o dokładnie tej
  nazwie, którą podałeś. Rozpoznawanie skrótów działa jak dotąd — `M42` nadal trafia w `NGC1976`.
  Z wiersza poleceń: `horreum target <baza> <nazwa> --clear`.

### Zmienione
- **Procent rozpoznanych obiektów przestał się zawyżać.** Licznik brał każdą klatkę, która ma
  obiekt — także rozpoznaną po współrzędnych, bez nazwy w nagłówku — a dzielił przez klatki,
  które nazwę mają. Te „darmowe" klatki podnosiły wynik i **maskowały spadek**: gdy przybywało
  klatek nierozpoznanych, procent osuwał się wolniej, niż powinien. Teraz obie strony ułamka liczą
  to samo, więc liczba mówi wprost, ile nazw program rozpoznał. Klatki rozpoznane bez nazwy nie
  znikają — stoją obok, z własną liczbą, na wszystkich trzech ekranach (Dostawa, wiersz poleceń,
  raport akceptacyjny). **Wynik po tej zmianie bywa niższy niż wczoraj — to ta sama biblioteka,
  mierzona uczciwiej.**
- **Wydawanie na stół ostrzega, gdy w katalogu docelowym stoi już drzewo o innym układzie.**
  Program zapisywał kształt drzewa obok niego od początku, ale nigdy go nie czytał — a ponowne
  wydanie z innym układem dokłada drugie drzewo obok starego (te same pliki policzone dwa razy).
  Ostrzeżenie pojawia się i przy podglądzie, i przy tworzeniu; decyzja zostaje po Twojej stronie.
- **Import z dawcy kończy tę samą drogę, co „Przetwórz wszystko".** Dotąd zatrzymywał się na
  rozpoznaniu obiektów, więc baza zaraz po imporcie nie miała jeszcze przepisów kalibracji ani
  powiązania klatek z masterami. Teraz przechodzi cały łańcuch i raport pokazuje oba etapy.

## [0.5.1] — 2026-08-01

Szlif po pierwszym realnym spotkaniu planera z archiwum: liczby dają się skanować wzrokiem,
ekrany nie kłamią pustą ramką, a lista nieczytelnych kopii mówi wreszcie DLACZEGO.

### Zmienione
- **Liczby w listwie facetów stoją w jednej kolumnie.** Godziny naświetlenia obiektu mają teraz
  własną kolumnę przy prawej krawędzi, więc licznik „(n)" kończy się w tym samym miejscu w każdym
  wierszu — wcześniej przesuwała go szerokość godzin („(301) · 60,4 h" kontra „(60) · 3,0 h")
  i kolumny liczb nie dało się przebiec wzrokiem.
- **Lista zadań w Porządkach ma wysokość swojej treści.** Ramka sięgała dotąd dołu strony, więc
  pod pięcioma wierszami zostawało kilkaset pikseli obramowanej pustki, która czytała się jako
  „coś tu miało być".
- **Zadanie bez roboty nie krzyczy.** Na wyszarzonym wierszu (n=0) liczba przestała być pogrubiona —
  pogrubienie zostaje tam, gdzie faktycznie jest co zrobić.
- **Lista „Kopie nieczytelne" mówi teraz, DLACZEGO** kopii nie da się przeczytać — nowa kolumna
  „Powód" z zapisem z dziennika (np. „ParseError: not well-formed…" dla uszkodzonego pliku XISF).
  Wcześniej ekran pokazywał tylko, KTÓRA kopia wypadła, a diagnoza leżała w dzienniku, poza
  zasięgiem wzroku. Pełny zapis zostaje pod kursorem; kopia przemianowana po awarii pokazuje „—",
  bo powód pożyczony od innej kopii byłby zmyśleniem.

### Naprawione
- **Kolumna „Powód" mieści się w oknie.** Ścieżka archiwum bierze teraz tylko tyle miejsca, ile
  zostaje, więc diagnoza stoi na ekranie zamiast za prawą krawędzią — wcześniej stuznakowa ścieżka
  rozpychała panel i powód, dla którego cała lista powstała, wymagał przewinięcia w bok.
- **Ścieżki w prawym panelu Przeglądu obiektów znów są czytelne.** Skrócona ścieżka pokazuje
  początek katalogu, a nie samo „R:…" — panel skracał ją do dwóch znaków niezależnie od tego, ile
  miejsca realnie miał. Pełna ścieżka wciąż jest pod kursorem.

## [0.5.0] — 2026-08-01

Planer celów: odpowiedź na pytanie „co dziś mam na niebie, w odpowiedniej wielkości i odpowiednich
filtrach" — z katalogu, Twojego sprzętu, nocy i tego, co już masz w archiwum.

### Dodane
- **Planer celów** — nowe, czwarte miejsce w oknie. Dla wybranej nocy pokazuje cele katalogu wraz
  z oknem widoczności, kulminacją, kadrowaniem w Twoich zestawach (jeden kadr albo mozaika z liczbą
  paneli), pokryciem z archiwum per kanał (RGB/Ha/OIII/SII), kosztem czasu narzuconym przez Księżyc
  i radą, co dziś warto zrobić. Cele nigdy nie fotografowane są **w wynikach**, nie poza nimi.
- **Kuratela celów**: status (zaplanowany / w toku / zrobiony / pominięty), priorytet i notatka —
  Twoje zdanie o celu, zapisywane wprost, nigdy wywnioskowane. `horreum target` robi to samo z wiersza
  poleceń.
- **Park teleskopów** — jawna deklaracja, czym dziś fotografujesz (okno: przycisk „Park…", wiersz
  poleceń: `horreum park`). Program tego NIE zgaduje z ostatniej klatki: „ostatnio używany" to nie to
  samo co „posiadany", a plan liczony historycznym sprzętem byłby planem cudzej nocy.
- **`horreum plan`** — pełna odpowiedź planera bez okna, z wyjściem czytelnym dla człowieka i `--json`
  dla skryptów.
- **Katalog celów w pakiecie** (~1200 obiektów wykonalnych Twoim sprzętem, warstwa rdzenia + osobna
  warstwa mgławic rozciągłych LBN/LDN). Aplikacja **nigdy nie sięga do sieci** — katalog jest plikiem
  w pakiecie, odświeżanym podmianą assetu; osobny skrypt deweloperski buduje go z OpenNGC.
  Pochodzenie i licencje danych: `horreum/data/PROVENANCE.md`.
- **Przejście z planera do Zbiorów**: „Pokaż klatki celu" ustawia filtr obiektu — także gdy ten sam
  cel leży w archiwum pod kilkoma nazwami naraz (np. `IC410` i `LBN807`); zobaczysz sumę, nie jedną
  z nich.

### Zmienione
- **Kolejka „do przeglądu" mówi całą prawdę**: klatki bez ŻADNEJ nazwy w nagłówku mają teraz własny
  kubełek. Wcześniej były widoczne w Zbiorach, ale kolejka o nich milczała (w archiwum autora: 25).
- **Scalenie teleskopów nie gubi parku** — deklaracja idzie za sprzętem; dwa sprzeczne zdania
  o jednym sprzęcie kończą się odmową, nie cichym wyborem jednego z nich.

### Naprawione
- **Program mówi prawdę o swojej wersji.** Numer widnieje teraz w **tytule okna** —
  wydanie jedzie do Ciebie jako jeden plik `horreum-gui.exe`, więc okno jest jedyną powierzchnią,
  na której da się sprawdzić, co masz. Wcześniej `horreum --version` w wydaniu 0.4.0 odpowiadał
  `horreum 0.3.2`: numer był wpisany z ręki w dwóch miejscach naraz i rozjechał się o dwa wydania.
  Teraz jest jeden, czytany.

## [0.4.0] — 2026-07-23

Angielski interfejs, ręczne przypisanie obiektu, wykrywanie zniknięć kopii, oś kalibracji z rodowodem
light↔master, szablony zmiany nazw, obsługa plików RAW oraz zapis nagłówków XISF. Dystrybucja Windows
jako pojedynczy plik `.exe`.

### Dodane
- **Angielski interfejs.** Przełącznik języka w menu **Widok → English** (zmiana po ponownym
  uruchomieniu). Polski pozostaje domyślny; wartości domenowe (nazwy obiektów, filtrów, teleskopów)
  zostają w oryginale, tłumaczy się warstwę okna.
- **Ręczne przypisanie obiektu** z kolejki „do przeglądu": klatce bez rozpoznanej nazwy można nadać
  obiekt wprost, ze szczeblem aliasu — z pierwszeństwem przed rozpoznaniem automatycznym. (Zapowiadane
  w 0.3.0 jako „w przygotowaniu".)
- **Wykrywanie zniknięć kopii.** Osobny przebieg sprawdza, które pliki zniknęły z dysku (z dowodem per
  plik — brak dostępu to „nie wiem", nie „nie ma"), pokazuje je w raporcie Dostawy oraz w nowej
  perspektywie **„Zniknięte"** w Zbiorach. Zapis stanu jest jawnym gestem, nie efektem ubocznym skanu.
- **Rozpoznawanie kompleksów po współrzędnych.** Obiekty rozciągłe bez jednego numeru katalogowego —
  jak kompleks Veil, czyli Pętla Łabędzia (NGC6960 + NGC6979 + NGC6992 + NGC6995) — są rozpoznawane po
  tym, **gdzie celował teleskop**, a nie po nazwie w nagłówku. Zdejmuje to z listy „do przeglądu" 250
  klatek, w tym **83 bez żadnej nazwy w nagłówku**. Rozpoznawalność obiektów na klatkach światła:
  97,2% → 99,0%. Definicje kompleksów są danymi (`horreum/resolve/data/regions.json`) — kolejny
  dopisuje się bez zmiany kodu. Nazwa z nagłówka zawsze wygrywa ze współrzędnymi.
- **Oś kalibracji i rodowód.** Nowy etap **„Kalibracja"** i **„Rodowód"** w łańcuchu Dostawy (oraz
  `horreum calibrate` / `horreum lineage`): program odczytuje przepis masterów (gain / offset /
  temperatura) i łączy każdy light z pasującym masterdarkiem i masterflatem — najbliższym czasowo.
  Przepis nieobecny w nagłówku jest odzyskiwany ze ścieżki pliku (jedyny, wąski i jawny wyjątek od
  zasady „nagłówek jest źródłem prawdy").
- **Szablony zmiany nazw.** Zmiana nazw działa na szablonie z tokenów (fragmenty ścieżki, wzorce ze
  starej nazwy), z edytorem rzędów w pasku i osobnym wzorem per typ pliku.
- **Obsługa plików RAW z aparatów** (`.dng` / `.arw` / `.cr2`): odczyt EXIF jako trzeci format wejścia
  obok FITS i XISF.
- **Interakcja z mapą stanowisk**: klik w punkt zaznacza stanowisko, najechanie pokazuje etykietę
  (nakładające się punkty klastra rozsuwają się do odczytu).
- **Masowe wydanie projekcji z okna** („Wydaj na stół") na wątku tła — z paskiem postępu, przerwaniem
  i szacowanym czasem.

### Zmienione
- **Zapis nagłówków obejmuje pliki XISF** (wcześniej tylko FITS) — korekta pól nagłówka masterów
  z zachowaniem tożsamości pliku i pełnym, bajtowym cofnięciem.
- **Klatki dark i bias nie trafiają już na oś teleskopu ani do konfiguracji** — z definicji nie zależą
  od optyki, więc ich brak przypisania to stan docelowy, a nie zaległość do przeglądu.
- **Dystrybucja Windows jako pojedynczy plik `.exe`** (onefile): jeden `horreum-gui.exe`, bez folderu
  obok — wystarczy pobrać i uruchomić.

### Naprawione
- Zawieszanie się aplikacji przy zamykaniu długich operacji (zakleszczenie wątków roboczych).
- Domknięcie bramek importu z bazy‑dawcy: spójność rodzajów klatek i kompletność zeznania.
- Czytelniejszy powód pominięcia przy zmianie nazw, gdy brak i daty w nagłówku, i czasu w nazwie pliku.

## [0.3.2] — 2026-07-20

Poprawki kolejki przeglądu (rzetelny licznik, trwały ślad nieczytelnej kopii) oraz dopieszczenie
list: liczby i godziny czytają się teraz jako kolumna, nie jako ogon nazwy.

### Zmienione
- **Listy pokazują liczby w osobnej kolumnie po prawej.** Dotyczy listwy filtrów w Zbiorach
  (obiekt, filtr, rodzaj, teleskop, noc), listy zadań w Porządkach i panelu „Pola". Wcześniej
  liczba i godziny naświetlania doklejały się do nazwy jednym ciągiem: najdłuższa pozycja
  rozpychała listę i wymuszała poziomy pasek przewijania, przez co „1.5 h" bywało ucięte, a godzin
  nie dało się porównać wzrokiem między wierszami. Teraz nazwa skraca się wielokropkiem, a liczba
  zostaje zawsze w całości.
- Godziny naświetlania przy obiekcie mają wagę drugorzędną — nazwa obiektu prowadzi wzrok, godziny
  jej nie konkurują.
- Porządki: liczba przy zadaniu jest pogrubiona, a zadania z zerem wyszarzone — „nic do zrobienia"
  widać bez czytania liczby (pozycja zostaje klikalna, bo to jedyna droga do danego ekranu).

### Naprawione
- Licznik zbioru odmienia się po polsku: „1 klatka" zamiast „1 klatek" (ścieżka Duplikatów robi
  z pojedynczej klatki przypadek typowy).
- Pusty widok Zbiorów na **pustej bazie** proponuje przyjęcie dostawy zamiast zmiany filtra —
  wcześniej odsyłał do filtrowania czegoś, czego jeszcze nie ma.
- Liczniki pokrycia w panelu „Pola" nie są już ucinane przy węższym oknie.
- Licznik „do przeglądu" w raporcie dostawy liczy **stan**, nie zdarzenia z dziennika — powtórna
  dostawa bez realnych zmian nie zawyża go już liniowo (7 klatek pokazywało się jako 35 po pięciu
  przebiegach). Raport podaje teraz liczbę klatek (distinct) i powody, które się nakładają; klatka
  z czytelnym nagłówkiem, ale nierozpoznanym rodzajem, przestała być cichym pominięciem.
- Kopia, która **stała się nieczytelna** przy re-skanie (transient NAS, bajty niezmienione), zostawia
  teraz trwały znacznik w stanie — kolejka przeglądu pokazuje ją jako „kopia nieczytelna" (jak dziś
  „bez nagłówka"), a skan przyrostowy re-czyta oznaczoną kopię do skutku (znacznik gaśnie dopiero po
  udanym odczycie). Wcześniej alarm milkł po jednym przebiegu i nie było go widać w stanie (#13).

## [0.3.1] — 2026-07-18

Dopieszczenie dystrybucji Windows.

### Dodane
- Ikona aplikacji (astro — złota gwiazda) widoczna na skrótach, pasku zadań i w instalatorze.
- Instrukcja użytkownika dołączona do instalatora jako PDF (skrót „Instrukcja" w menu Start).

## [0.3.0] — 2026-07-18

Redesign UX aplikacji okienkowej (F1–F8) i mapa stanowisk — po pniu scalenia `v0.2`.

### Dodane
- **Nawigacja 3 miejsc** (F5): pasek boczny **Dostawa / Zbiory / Porządki** zamiast zakładek;
  osie teleskop/obserwatorium/obiekt jako podstrony Porządków; licznik zadań przy „Porządki".
- **Motyw ciemny / jasny** (F6): przełącznik w menu **Widok**, pamiętany między uruchomieniami.
- **Listwa facetów** (F4): zawężanie po wartościach z policzonymi wystąpieniami (sibling‑set).
- **Portfel naświetleń** (F7): sumaryczne godziny lightów per obiekt × filtr w listwie facetów.
- **Przyjmij nowe** (F2): cała sekwencja skan → grupuj → rozwiąż → delta jednym kliknięciem,
  na zapamiętanym katalogu źródłowym.
- **Filtr negatywny** (F1) i **pasek zbioru** z panelami operacji na plikach (F3).
- **Mapa stanowisk** (F8): graficzny rzut współrzędnych GPS osi obserwatorium na konturach
  świata (Natural Earth).
- **Dokumentacja**: dwujęzyczny README (angielska witryna wystawowa + polski przewodnik) ze
  zrzutem głównego okna, CONTRIBUTING oraz instrukcja użytkownika w `doc/`.

### Naprawione
- Paczka zamrożona: przypięty `PySide6==6.9.2` + kontrola obecności pluginu `qwindows` + smoke‑start GUI
  (stare archiwum startowało bez pluginów Qt).
- Listwa facetów zachowuje pozycję przewijania przy przeładowaniu.

### W przygotowaniu
- Ręczne przypisywanie obiektu do klatek z kolejki przeglądu.

## [0.2] — 2026-07-04

Pień scalenia trzech osi tożsamości + aplikacja okienkowa + dystrybucja Windows.

### Dodane
- **Oś obiektu**: resolver katalogów krzyżowych (Messier / Caldwell → NGC / IC), nazw potocznych,
  ciał Układu Słonecznego i komet (dopasowanie z nagłówka, nie z nazwy pliku).
- **Oś obserwatorium**: stanowisko wyprowadzane ze współrzędnych GPS w nagłówku (scal / nazwij).
- **Widok „Klatki"** (Zbiory): siatka nad nagłówkami z filtrem i perspektywami
  (Przegląd / Kalibracja / Duplikaty / Do przeglądu).
- **Nazwy z faktów**: zmiana nazw plików wyprowadzana z faktów w bazie (podgląd domyślny;
  wykonanie i cofnięcie jawne) — GUI i `horreum rename`.
- **Projekcje**: materializacja perspektywy w drzewo linków/kopii pod WBPP (podgląd domyślny;
  wykonanie jawne) — GUI i `horreum project`.
- **Zapis nagłówków** (writeback): korekta pól nagłówka jako osobna, jawna klinga zapisu plików.
- **Dystrybucja Windows**: zamrożony artefakt onedir (`horreum-gui.exe` + `horreum.exe`),
  skrypt budujący z izolowanego środowiska.

## [0.1] — 2026-07-03

Fundament: przejście na model „baza = autorytet, `sha1` = tożsamość".

### Dodane
- **Skan** drzewa FITS/XISF z odczytem nagłówków (append‑only, bez modyfikacji plików).
- **Schemat rdzenia** oparty na tożsamości treści (`sha1` danych), historia zmian jako zdarzenia.
- **Grupowanie** osi teleskopu i konfiguracji sprzętu po skanie.
- **Import zasilający** świeżej bazy z bazy‑dawcy (read‑only).
- **CLI**: `init` / `scan` / `group` / `resolve` / `delta`.

[Niewydane]: https://github.com/abo-t/horreum/compare/v0.5.1...HEAD
[0.5.1]: https://github.com/abo-t/horreum/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/abo-t/horreum/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/abo-t/horreum/compare/v0.3.2...v0.4.0
[0.3.2]: https://github.com/abo-t/horreum/compare/v0.3.1...v0.3.2
[0.3.1]: https://github.com/abo-t/horreum/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/abo-t/horreum/compare/v0.2...v0.3.0
[0.2]: https://github.com/abo-t/horreum/compare/v0.1...v0.2
[0.1]: https://github.com/abo-t/horreum/releases/tag/v0.1
