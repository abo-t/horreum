# Historia zmian

Format wzorowany na [Keep a Changelog](https://keepachangelog.com/pl/1.1.0/).
Wersjonowanie [semantyczne](https://semver.org/lang/pl/). Projekt jest we wczesnym rozwoju —
schemat i API mogą się jeszcze zmieniać.

## [Niewydane]

## [0.23.0] - 2026-10-28

Wydanie o **Planerze, który nie gubi wpisu, Porządkach z klawiatury i szufladzie, która daje „Cofnij” także po
„Odrzuć”, dla zmiany nazw po restarcie i po przerwanym zapisie w oknach kart**. Niezapisany status, priorytet
i notatka celu przeżywają klik chipa i przeliczenie planu. Enter na wierszu Porządków działa jak klik. Okna wyboru
folderu i pliku nie startują już w katalogu programu. Zbiory malują się szybciej, a pierwsze wejście na stronę mówi,
że strona się przygotowuje. **Schemat bazy bez zmian (47)** - baza otwarta w 0.20.0, 0.21.0 albo 0.22.0 otwiera się
tak samo; baza ze starszej wersji przechodzi tę samą migrację co w 0.20.0, więc przed pierwszym uruchomieniem zrób
kopię pliku bazy.

### Dodane

- **Porządki z klawiatury:** Enter na wierszu listy działa jak klik (przytrzymany klawisz nie powtarza gestu).
  Wejście w Porządki klawiaturą z paska nawigacji kładzie fokus na liście albo na „← Porządki” otwartej podstrony,
  a „← Porządki” (klik, Return albo Enter z klawiatury numerycznej) wraca na ten sam wiersz.
- **„Cofnij” ostatniego zapisu po „Odrzuć”:** odrzucenie zmian w szufladzie stawia z powrotem „Cofnij” ostatniego
  zapisu - kart albo nazw, zależnie od tego, który był nowszy. Po ponownym otwarciu programu szuflada proponuje
  także ostatnią zmianę nazw („Ostatnia zmiana nazw z RRRR-MM-DD: N plików”); gdy historii zmian nazw nie da się
  jednoznacznie przypisać, szuflada mówi to wprost zamiast proponować „Cofnij”.
- **„Cofnij” po przerwanym zapisie w oknach kart:** gdy błąd przerwie zapis w oknie „Zatwierdź obiekty ze ścieżek”
  albo „Napraw nagłówek…” po podmianie części plików, okno mówi „N z M zapisane, potem błąd … - „Cofnij” cofa
  zapisane” i daje „Cofnij” zapisanych plików; po zamknięciu okna ten sam zapis cofa recepta na pasku.
- **„Przygotowuję stronę „…”…”:** pierwsze wejście w Zbiory, Dostawę albo Planer, które buduje stronę, pokazuje to
  zdanie na pasku z kursorem oczekiwania (nazwa strony jak w pasku bocznym). Dawniej klik w Zbiory wpadał w ~320 ms
  budowy bez słowa.
- **Pusty plan Planera mówi, co wyzerowało listę** - filtr statusu, próg kosztu, wysokość albo rozmiar i magnitudo;
  „Przywróć domyślne” zdejmuje też filtr statusu.

### Zmienione

- **Okna wyboru folderu i pliku** (dziesięć okien, m.in. żniwa, Dostawa, „Otwórz bazę…” i „Nowa baza…”) startują
  w ostatnio użytym miejscu, które istnieje, a na końcu w folderze domowym - nigdy w katalogu uruchomienia programu.
  Sprawdzenie dysku sieciowego ma limit czasu i nie zatrzymuje okna. „Otwórz bazę…” i „Nowa baza…” startują przy
  bieżącej albo ostatniej bazie.
- **Liczba progu Planera jednym zapisem:** tytuł paska, dopisek wartości domyślnej, podpowiedź resetu, próg kosztu
  i pusty stan pokazują próg z precyzją wpisu („≥6.5′ (domyślnie 6′)”, „13 mag”).
- **Gesty zapisu Planera w biegu Dostawy** mówią w podpowiedzi, dlaczego są wygaszone; po biegu wracają ich
  własne podpowiedzi. Koniec biegu Dostawy ze żniwami odświeża widoki jeden raz.
- **Zdanie odmowy uzgodnienia z dyskiem w szufladzie** - gdy plik zmienił się na dysku i rozstrzyga człowiek - jest
  krótkie: powód, co zrobić i nazwa pliku na końcu, czasy w strefie lokalnej. Pełny powód (czas UTC, pełne ścieżki)
  zostaje w szczególe pola wyniku. Pozostałe odmowy podają nazwy plików zamiast pełnych ścieżek.
- **Cofnięcie mówi „N nie niesie wersji z tego zapisu - nie ma czego cofać”** o plikach, w których nie ma wersji
  z tego zapisu (np. podmiana pliku nie została potwierdzona), zamiast liczyć je jako już cofnięte - w oknach kart,
  szufladzie, na pasku i w `horreum header-fix --undo`.
- **Zdanie błędu systemu** nie zaczyna się od nazwy klasy Pythona („OSError: [WinError …]”) - klasa trafia do
  szczegółu błędu.
- **Szuflada przy nieznanych faktach zapisu** nie pokazuje „Cofnij”, a zdanie kończy się informacją z numerem
  commitu - tak jak okna kart.
- **Jedna reguła cofnięcia zapisu kart** dla szuflady, Porządków, osi obiektu i wiersza poleceń; wiersz Porządków
  „Niedokończone cofnięcia zapisu kart” liczy się mniejszą liczbą zapytań z tym samym wynikiem.
- **Menu „Więcej…” na Domu:** pozycja „Wciągnij z WBPP…” mówi w podpowiedzi, dlaczego żniwa są teraz niedostępne.
- **Szybsze Zbiory** (pomiar natywny na bazie ~17 000 klatek): kadr widoku klasycznego 47,7 → 28,5 ms,
  Znajdź 25,0 → 16,8 ms, klik w kafel Znajdź ~158 → ~97 ms; szerokość kolumny ścieżki z treści 107,8 → 29,0 ms.

### Naprawione

- **Planer gubił niezapisany wpis:** status, priorytet i notatka celu ginęły przy kliku chipa soczewki,
  „Porządek” albo przeliczeniu planu w tle, a notatka jednego celu mogła trafić do innego.
- **Zapis w Zbiorach i na osi obiektu naraz:** koniec jednego zapisu odblokowywał gesty Dostawy, Przyjmij, Domu
  i żniw, choć drugi jeszcze trwał. Teraz gesty czekają na koniec ostatniego zapisu.
- **Odłożone recepty osi obiektu** (cofnięcie kart, cofnięcie dopisania teleskopu) niosą tożsamość z chwili
  złożenia i odmawiają, gdy stan się zmienił, zamiast trafiać w inny.
- **Odmowa żniw w trakcie sprawdzania folderu źródła** odsyłała do postępu na stronie Dostawy, którego wtedy nie ma -
  teraz mówi „Dostawa sprawdza folder źródła - przyjmij po zakończeniu sprawdzania”.
- **Porażka budowy Dostawy po oknie żniw** mówi utratę rodowodu na początku zdania.
- **Zdanie o klatkach bez dowodu po cofnięciu zapisu kart** liczy klatki przy obiekcie z każdego źródła nazwy
  w nagłówku, nie tylko z jednego.
- **Zapis perspektywy po samym przewinięciu** utrwalał szerokość kolumny ścieżki policzoną przez program jako wybór
  ręki; gest ręki wygrywa też z resetem bez zbioru.

## [0.22.0] - 2026-10-27

Wydanie o **Planerze, który mówi, od czego odchylono progi, Porządkach bez zamrożenia okna i cofnięciu zapisu kart,
które przeżywa restart i mówi, co zostało**. Tytuł paska progów Planera podaje wartość domyślną przy każdym zmienionym
progu, a noc planu wybiera przełącznik „bieżąca noc”. Wejście w Porządki nie zatrzymuje okna - liczby dochodzą w tle.
Po ponownym otwarciu programu ostatni zapis kart cofa się jednym „Cofnij” w szufladzie. **Schemat bazy bez zmian
(47)** - baza otwarta w 0.20.0 albo 0.21.0 otwiera się tak samo; baza ze starszej wersji przechodzi tę samą migrację
co w 0.20.0, więc przed pierwszym uruchomieniem zrób kopię pliku bazy.

### Dodane

- **„Cofnij” ostatniego zapisu kart po ponownym otwarciu programu:** szuflada zmian pokazuje ostatni przebieg zapisu
  kart zdaniem „Ostatni zapis kart z RRRR-MM-DD: N plików - „Cofnij” cofa cały przebieg” z przyciskiem „Cofnij”.
  Dawniej po zamknięciu okna zostawała tylko droga przez wiersz poleceń. Nowa zmiana w szufladzie zdejmuje to zdanie,
  a „Ponów nieudane (N)” tego samego przebiegu wraca obok.
- **Przełącznik „bieżąca noc” w wierszu „Noc” Planera:** zaznaczony domyślnie - plan liczy się na bieżącą noc i noc
  nie trafia do ustawień; wybór daty w polu zdejmuje przełącznik. Zastępuje pole startujące od daty 1970: Tab wychodzi
  z pola, a kalendarz otwiera się na bieżącej nocy.
- **Cofnięcie zapisu kart mówi o klatkach bez dowodu:** gdy po cofnięciu dopisania karty `OBJECT` klatka zostaje przy
  obiekcie z nagłówka, a nie ma dowodu, że nadała go cofnięta karta, zdanie wyniku podaje ich liczbę zamiast milczeć.

### Zmienione

- **Tytuł paska progów Planera** dopisuje wartość domyślną przy zmienionym progu („rozmiar ≥8′ (domyślnie 6′)”) oraz
  człony „koszt ≤N” i „status: …” przy włączonym progu kosztu i filtrze statusu; pełny tekst stoi w podpowiedzi.
- **Planer w biegu Dostawy:** gasną wyłącznie gesty zapisu do bazy (zapis i zdjęcie celu, „Park…”, sieroty) - plan
  zostaje czytelny i sortowalny, a progi czynne; po końcu biegu plan liczy się dokładnie raz. Lista „Porządek” i chipy
  zestawów nie gubią fokusu ani otwartej listy przy przeliczeniu.
- **Wejście w Porządki** nie zatrzymuje okna: liczniki liczą się w tle (klik „Porządki” blokował okno ~1,1 s, teraz
  ~20 ms; pomiar natywny, mediana). Do wyniku lista wygląda jak przy pierwszym montażu, a klik w wiersz w tym czasie
  wykona się po przyjściu liczb - wyjście z listy go odwołuje.
- **Zdania szuflady:** zapis w przebiegu z wcześniejszymi plikami mówi „N zapisane teraz · … · razem M w przebiegu”;
  długie zdanie skraca się wielokropkiem w środku, a początek i „(commit N)” zostają widoczne (całość w podpowiedzi);
  odmowa uzgodnienia nazw podaje drogę dla każdego powodu.
- **Okna kart** („Zatwierdź nazwy ze ścieżki”, „Napraw nagłówek”) pokazują „Cofnij” tylko wtedy, gdy zadziała: po
  zapisie przerwanym w miejscu bez przycisku, po niepotwierdzonej podmianie pliku z „do sprawdzenia”, a gdy stanu
  zapisu nie da się odczytać - ze zdaniem zamiast przycisku.
- **`horreum header-fix --undo 1,2`** cofa cały przebieg tą samą drogą co „Cofnij” w szufladzie (najpierw sprawdza, że
  podane commity należą do jednego przebiegu).
- **Wiersz Porządków „Niedokończone cofnięcia zapisu kart”** liczy się szybciej (na bazie z 220 cofnięciami ~4,5 s →
  ~20 ms) z tym samym wynikiem.
- **Okno żniw:** pierwszy wybór folderu startuje w polu, w archiwum albo w folderze domowym, nie w katalogu uruchomienia
  programu.

### Naprawione

- **Pole „Noc” Planera:** naciśnięcie ramki pola przestawiało noc o dobę albo rok i zdejmowało przełącznik „bieżąca
  noc”, więc plan liczył się dla złej nocy (pole daty z kalendarzem w Qt 6.9.2). Klawisze, kółko z fokusem i kalendarz
  działają jak dawniej, wygląd pola bez zmian.
- **Cofnięcie przerwane w każdej drodze** (szuflada, okno kart, wiersz poleceń) zostawia ślad i pokazuje się
  w Porządkach jako „Dokończ cofnięcie”; cofnięcie domknięte do końca z listy wypada.
- **Błąd wzoru nazwy:** nieprawidłowe wyrażenie w szablonie daje zdanie z powodem zamiast „NoneType”, szczegół błędu
  wyrażenia trafia do szuflady w każdej drodze, odmowa mówi etykietą tokenu z edytora, a pozycja spoza edytora pokazuje
  się jako „folder: poziom …”.

## [0.21.0] - 2026-10-26

Wydanie o **kółku myszy, które nie zmienia pól bez kliknięcia, i „Cofnij”, które cofa cały przebieg szuflady**.
Kółko nad polem bez fokusu przewija listę zamiast przestawiać próg Planera albo filtr. „Cofnij” w szufladzie cofa
wszystkie zapisy przebiegu, także te sprzed restartu okna, a nieudane pliki można postawić ponownie jednym gestem.
Wejście w Znajdź z Domu nie zatrzymuje okna. **Schemat bazy bez zmian (47)** - baza otwarta w 0.20.0 otwiera się
tak samo; baza ze starszej wersji przechodzi tę samą migrację co w 0.20.0, więc przed pierwszym uruchomieniem zrób
kopię pliku bazy.

### Dodane

- **„Ponów nieudane (N)” w szufladzie zmian:** po zapisie, w którym część plików się nie udała (np. plik zajęty),
  gest stawia nieudane pliki ponownie w tym samym przebiegu - kart i nazw - a „Cofnij” cofa potem cały przebieg.

### Zmienione

- **„Cofnij” cofa cały przebieg szuflady:** wszystkie jego zapisy od najnowszego, także zapis sprzed restartu okna
  i sprzed „Anuluj”. „Cofnij” stoi także po „Odrzuć”, po zamknięciu przebiegu do zera i po operacji bez podmiany
  pliku. Cofnięcie przerwane między zapisami przebiegu widać w Porządkach jako „Dokończ cofnięcie”.
- **Zapis przerwany awarią w połowie** mówi w szufladzie jednym zdaniem „zapisano N z M, …” zamiast „Zatwierdzono: N”
  obok porażki; zapis rozdarty bez możliwości cofnięcia podaje drogę odzysku.
- **Znajdź:** szerokości kolumn liczone z metryki fontu zamiast mierzenia każdej komórki - klik w kafel Znajdź
  z Domu ~550 → ~180 ms (pomiar natywny, mediana), bez przestoju okna. Szerokości dopasowują się także do zbioru,
  który przy wejściu był jeszcze w drodze; szerokość ustawiona ręką na kolumnie wygrywa.
- **Planer w biegu Dostawy** liczy się raz, po końcu biegu, i mówi to zdaniem w nagłówku nocy.
- **„Wciągnij z WBPP…” z Domu** nie buduje ekranu Dostawy, gdy bieg jest niemożliwy - powód odmowy idzie od razu.
- **Główny przycisk Dostawy** zostaje pogrubiony razem z wyróżnieniem po każdej zmianie motywu.

### Naprawione

- **Kółko myszy zmieniało pole bez kliknięcia:** kółko nad progami Planera, „Park…”, wzorem nazwy i filtrami
  przewijało wartość pola pod kursorem, więc próg Planera dało się przestawić przy przewijaniu listy. Teraz kółko
  zmienia pole tylko wtedy, gdy pole ma fokus (po kliknięciu); bez fokusu przewija listę pod kursorem.
- **Wzór nazwy z tokenem spoza słownika** pokazuje się wiernie (token obcy, poziom folderu spoza pola), a „Podgląd”
  mówi zdaniem z kodem przy nieprawidłowym wyrażeniu albo poziomie folderu zamiast błędu programu.
- **Recepty paska po powrocie do okna:** aktywacja okna zdejmuje z paska recepty, które przestały być aktualne (po
  innym oknie, po zamknięciu okna dialogowego).
- **„Cofnij zapis (commit N)” odłożone przed podmianą pliku bazy** (np. przywróconą kopią pod tą samą ścieżką) nie
  cofa commitu innej biblioteki.
- **Okno Znajdź** sprząta wątek składu, gdy budowa ekranu się nie uda.

## [0.20.0] - 2026-10-26

Wydanie o **szufladzie, która przeżywa restart i mówi, co się stało, cofnięciu, które mówi, co zostało, i oknie,
które nie stoi**. Zmiany czekające w szufladzie wracają po ponownym otwarciu bazy, a zapis przerwany w połowie ma
zdanie i drogę dokończenia. Przerwane cofnięcie zapisu kart podaje, ile plików zostało w stanie po zapisie, a ile
wymaga sprawdzenia. Pisarz kart nie zmienia bajtów nagłówka bez słowa. Otwarcie bazy nie buduje od razu wszystkich
ekranów, a liczniki Porządków liczą się w tle. **Schemat bazy 45 → 47** (znacznik bajtu spoza ASCII w nagłówku
kopii, dziennik migracji): bazę otwartą w tej wersji 0.19.0 i starsze już nie otworzą - przed pierwszym
uruchomieniem zrób kopię pliku bazy.

### Dodane

- **Wiersz Porządków „Nagłówek z bajtem spoza ASCII”:** skan bada surowe bajty nagłówka kopii i oznacza nagłówek
  FITS z bajtem spoza drukowalnego ASCII (np. polski znak w komentarzu karty) - takiego nagłówka pisarz nie zmieni,
  więc Porządki mówią o nim przed zapisem. Dostawa ma przycisk „Sprawdź bajty nagłówków (N)” z szacunkiem czasu przed
  biegiem i tempem w biegu.
- **Dziennik błędów programu:** błąd programu trafia do pliku dziennika (z rotacją), zanim pokaże się okno błędu;
  menu „Pomoc → Otwórz dziennik błędów”. Okno błędu z miejscem w kodzie pojawia się także przy błędzie w czasie
  startu (budowa okna, otwarcie bazy startowej).
- **Wiersz Porządków „Dokończ cofnięcie (commit N)”** dla cofnięcia zapisu kart przerwanego w połowie. Gdy bazę
  trzyma inny proces Horreum (okno albo wiersz poleceń), wiersz mówi to z numerem procesu.
- **Wiersz poleceń pod blokadą szuflady:** `rename --apply/--undo`, `header-fix --apply/--undo` i `object-change`
  odmawiają (kod 2, baza nietknięta), gdy szufladę tej bazy prowadzi otwarte okno programu - z numerem procesu
  w zdaniu. Dotąd polecenie mogło zapisywać równolegle z oknem.
- **Sortowanie list Osi teleskopu i Osi obserwatorium:** klik nagłówka sortuje, drugi odwraca; liczby liczbowo,
  puste na końcu, porządek przeżywa odświeżenie. Gdy odświeżenie listy zamknie wpis w trakcie pisania, pasek mówi,
  że wpis nie został zapisany.
- **Oś teleskopu z Domu:** pozycja w menu „Więcej…”.

### Zmienione

- **Otwarcie bazy:** ekrany powstają przy pierwszym wejściu, a Zbiory dobudowują się zaraz po pierwszym pokazaniu
  okna (otwarcie archiwum ~17 tys. klatek, pomiar natywny: ~690 → ~190 ms). Liczniki Porządków liczą się w tle -
  „Porządki (…)” i faza liczenia przy tytule listy stoją do pierwszego wyniku, a klik w tym czasie wykonuje się po
  wyniku. Gdy liczenie się nie uda, plakietka Porządków i kafel Domu mówią „!” zamiast pokazywać zero.
- **Zmiana motywu** przemalowuje listę Porządków, kolejkę osi obiektu i optykę osi teleskopu bez przeliczania i bez
  zapisu do bazy.
- **Dostawa:** główny przycisk w ciemnym bursztynie z motywu; gdy wejście do Dostawy ma powód (fakty kopii, bajty
  nagłówków), wyróżnienie i fokus stoją na przycisku, którego ten powód wymaga, a podpowiedź wiersza Porządków nazywa
  ten przycisk jego napisem.
- **Cofnięcie zapisu kart mówi, co zostało:** przerwane cofnięcie podaje „N nietkniętych plików zostaje w stanie po
  zapisie, M wymaga sprawdzenia”; cofnięcie odmawia, gdy po cofanym zapisie przyszedł nowszy zapis tych plików,
  i przywraca stan obiektu klatki sprzed zapisu (także po „Rozwiąż”).
- **Recepty paska:** „Cofnij zapis (commit N)” zostaje na pasku Porządków po zamknięciu okna kart; w biegu Dostawy
  albo zapisu Zbiorów odmawia zdaniem z numerem commitu i poleceniem dla wiersza poleceń, a po końcu biegu wraca
  sama. Recepty odłożone w biegu przeżywają przełączenie bazy i znikają, gdy ten sam gest wykonano inną drogą
  (wiersz poleceń, drugie okno, Oś teleskopu). Recepty optyki i perspektyw przeżywają przeładowanie Zbiorów.
- **Szuflada zmian mówi, co się stało:** po zapisie w miejscu przerwanym zamknięciem procesu mówi zdaniem zapisu
  przerwanego zamiast „pusta”, a „Dokończ zapis” podejmuje przebieg; Dom mówi „odrzucono N zmian z poprzedniej
  sesji”. Przebieg wyczyszczony do zera zamyka się jak po „Odrzuć”; „◌” oznacza przebiegi czekające poza tą
  szufladą; pusta szuflada odświeża się przy pokazaniu, aktywacji okna i końcu Dostawy. Gdy uzgodnienie nazw
  odmówiło, szuflada podaje powód; pod blokadą innego okna mówi, który przebieg tam czeka. Zapis przerwany awarią
  w połowie (część plików zapisana) ma w szufladzie „Cofnij”.
- **Znajdź i Zbiory:** EXPTIME i „Czas” z najwyżej jednym miejscem po przecinku (pełna wartość w podpowiedzi);
  wiersz „Wersje stosów” liczy grupy; Shift+strzałka po sortowaniu idzie od kotwicy zaznaczenia.
- **„Zmień obiekt…”:** podgląd mówi prawdę dla każdej pozycji (RAW bez karty przenoszony według planu), „Nie
  rozpoznaję nazwy…” dopiero po pauzie w pisaniu, a po zamknięciu okna pasek mówi, ile klatek przeszło na jaki
  obiekt.
- **Okno wydania:** raport bez surowych znaczników technicznych; „Otwórz w Eksploratorze” po powrocie do wydanego
  obiektu, gdy folder istnieje.
- **Planer:** wyszukanie bez trafienia (np. „M 4” bez aliasu w katalogu) mówi to zdaniem, a trafienie przez alias
  pokazuje nazwę katalogową z aliasem („NGC1976 (M 42)”); szerokości kolumn bez przeliczania całej tabeli.
- **Listwa filtrów Zbiorów** dopasowuje listy, pole i tytuły do powiększonego fontu.
- **Szablon nazw** odrzuca nieznany token tym samym zdaniem co zapis nazwy.
- Przyciski okien systemowych Qt w języku interfejsu programu; przyciski okien Zbiorów i paska zbioru z katalogu
  tłumaczeń.

### Naprawione

- **Perspektywa „f/ niezgodna z teleskopem”:** podpowiedź z liczbą klatek do poprawy („RC8 200 → 8…”) zostaje na
  pasku po dołożeniu kolumny FOCRATIO, po przebiegu Dostawy i po powrocie do Zbiorów - dotąd znikała po niecałej
  sekundzie. Wejście w perspektywę zaraz po otwarciu bazy też dokłada kolumnę FOCRATIO. Klatki z poprawką f/
  czekającą w szufladzie nie wracają do podpowiedzi. Podpowiedzi gestu i wiersza Porządków nazywają przycisk
  szuflady jego słowem: „Zatwierdź”.
- **Pasek po oknach „Napraw nagłówek…” i „Zatwierdź ze ścieżki…”:** wynik udanego zapisu kart zostaje na pasku
  do następnego komunikatu (dotąd gasł po 5 s) i mówi, jak cofnąć commit z wiersza poleceń
  („… (commit 11) - cofnięcie: header-fix --undo 11”); pełne polecenie ze ścieżką bazy stoi pod kursorem
  i kopiuje się przez „Kopiuj szczegół”. Tak samo po nieudanym cofnięciu - zdanie nie niesie już ścieżki bazy,
  która ucinała numer commitu. Bieg w „Zatwierdź ze ścieżki…” zakończony bez przypisań (odmowa zapisu nazwy
  na pierwszej pozycji) też trafia na pasek razem z powodem odmowy, a wyniku nie przykrywa już zdanie o pustej
  bibliotece.
- **Szuflada zmian po restarcie:** zmiany czekające w szufladzie, gdy program zamknięto (także w połowie zapisu po
  „Anuluj”), wracają po ponownym otwarciu bazy („Z poprzedniej sesji czeka N zmian”) - „Zatwierdź” dokańcza zapis,
  „Odrzuć” zdejmuje tylko zmiany czekające, a wpisy już rozstrzygnięte (potrzebne do cofnięcia i do potwierdzenia
  skanem) zostają. Szufladę jednej bazy prowadzi jedno okno programu - drugie okno na tej samej bazie mówi to
  i niczego nie podejmuje. Zamknięcie okna w trakcie zapisu do plików nie zamyka już bazy pod pracującym zapisem.
- **Szuflada przy „0 zmian, N pominięto”:** zdanie stagingu i podglądu podaje przyczyny pominięć (najwyżej trzy,
  reszta liczbą) bez najeżdżania na komórki; stary wynik nie zostaje obok, a „Cofnij” znika dopiero wtedy, gdy coś
  naprawdę wchodzi do szuflady. Identyfikator zapisu stoi w zdaniu dokładnie raz także po gestach Dokończ zapis,
  Przywróć nagłówek, Zwolnij i Ta kopia prowadzi oraz w Nazwach.
- **Zbiory:** Shift+klik po sortowaniu liczy zakres od pierwszego kliknięcia (dotąd od ostatniego); podpis belki
  grupy jest widoczny po przewinięciu tabeli w poziomie.
- **Pisarz kart nie zmienia bajtów bez słowa:** nagłówek FITS z bajtem spoza drukowalnego ASCII (np. polski znak
  w komentarzu karty) jest odmawiany z nazwą karty i bajtu w każdej drodze zapisu i cofnięcia - dotąd pełny zapis
  zamieniał taki bajt na `?`, a zapis w miejscu mówił nieprawdę, że „nagłówek zmienił się od stagingu”. Odmowa
  z kodem także dla liczby, której pole karty FITS nie odtworzy (cyfry ucięte bez słowa), dla `nan`/`inf` i dla
  nieznanej operacji - jednym zdaniem w FITS i XISF, już w podglądzie makra. Zdania zapisu w miejscu wskazują gest
  z menu („Przywróć nagłówek sprzed zapisu”) zamiast nazwy funkcji programu; numer operacji stoi pod kursorem.
- **Błąd programu w oknach Domu, Dostawy, żniw, Pól i Porządków** mówi się jednym zdaniem w języku interfejsu
  (dotąd surowy tekst wyjątku po polsku także w UI angielskim), miejsce w kodzie stoi pod kursorem.
- **Dostawa ze źródłem o długiej ścieżce** nie poszerza okna ponad ekran - zdania ze ścieżką się zawijają (przy
  ścieżce ~200 znaków najmniejsza szerokość okna 2023 → 1424 px).
- **Odniesienie czasu stosu:** autocrop dziedziczy odniesienie po swoim oryginale (dotąd okno proponowało 0, bo
  autocrop zaczyna się sekundę wcześniej); przyciski okna odniesienia i okna nazwy celu wydania mówią w języku
  interfejsu.
- **„Zmień obiekt…” po cofnięciu gestu, który założył obiekt:** wybierak mówi, że zapis przywróci obiekt zdjęty
  cofnięciem.
- **Okno wydania:** przed „Utwórz” mówi, że manifestu nie da się teraz zapisać (uszkodzony, innego wydania, zajęty),
  także przy niepełnym drzewie; odmowa przy zajętym pliku roboczym podaje jego nazwę raz, pełna ścieżka stoi
  w szczególe. Polecenie `project` przy pierwszym dowiązaniu odmówionym radzi `--copy` zamiast przełącznika okna.
- **Pisarz kart** odmawia nagłówkowi FITS z `END` przed kanonicznym zakończeniem nagłówka - bajty pliku zostają
  nietknięte (dotąd dwa czytniki nagłówka mogły widzieć w takim pliku różne końce).
- **XISF:** gołą wartość logiczną karty czyta jeden parser; jawny indeks wystąpienia bierze starą wartość swojego
  wystąpienia.
- **Pole „Baza:”** zawija długą ścieżkę i od pierwszego układu mieści się albo kończy wielokropkiem; znak NUL w polu
  folderu wyjścia żniw mówi się błędem wejścia; przełączenie bazy w biegu zapisu odmawia bez anulowania biegu.

## [0.19.0] - 2026-10-20

Wydanie o **karcie liczbowej zapisanej w miejscu i Porządkach, które nie czekają na dysk**. Poprawka karty
liczbowej albo logicznej nagłówka FITS (wartość tego samego rodzaju co zastana) zapisuje się w miejscu, jak karta
tekstowa - plik nie jest przepisywany w całości, więc klatki wydane dowiązaniem do folderu roboczego WBPP widzą
poprawkę. Porządki nie sprawdzają plików archiwum w oknie: kopie zostawione obok ścieżki sprawdza przegląd w tle,
a udział, który nie odpowiada, nie zatrzymuje ani okna, ani zmiany bazy. Shift+klik po sortowaniu, grupowaniu
i podglądzie zaznacza tak, jakby zaznaczenie nigdy nie było odtwarzane. **Schemat bazy bez zmian (45):** bazę
otwartą w tej wersji dalej otworzą 0.17.0 i 0.18.0.

### Zmienione

- **Karta liczbowa i logiczna zapisuje się w miejscu** (okna kart i szuflada zmian), bajt w bajt tak, jak zapisałby
  ją pełny zapis - także przy zmianie samego komentarza karty. Karta o wartości równej zastanej zostaje w pliku
  nietknięta. Gdy plik trzeba przepisać w całości, podpowiedź wymienia każdy taki plik (do dziesięciu, reszta
  liczbą) i mówi, że dowiązanie twarde w wydaniu `_WBPP` zostało przy starej treści.
- **Porządki bez sprawdzania archiwum w oknie:** liczniki i lista nie dotykają plików archiwum. Kopie zostawione
  do oka sprawdza jeden przegląd w tle na bazę; gdy trwa dłużej niż 3 s, wiersz „Kopie zostawione do oka” mówi,
  że sprawdzanie trwa, a przy udziale, który nie odpowiada - że części plików nie dało się sprawdzić, z radą
  ponowienia po powrocie udziału. Nazwa, której brak przegląd dowiódł, znika z listy. Zamknięcie okna i zmiana
  bazy nie czekają na udział.
- **Zaznaczenie w Zbiorach:** Shift+klik po sortowaniu, grupowaniu, podglądzie i przeładowaniu dokłada zakres do
  całego zaznaczenia, a nie tylko do jego części sprzed odtworzenia; bieżąca komórka wraca na swoje miejsce także
  na wierszu niezaznaczonym.
- **Prawy klik w tabeli klatek:** na klatce spoza zaznaczenia zaznacza wyłącznie ją i otwiera menu; na klatce
  zaznaczonej zaznaczenie zostaje; Ctrl i Shift tej reguły nie zmieniają.
- **Szuflada zmian po zapisie:** zbiór i podgląd zmian odświeżają się jednym przeładowaniem, panel Rodowód zostaje
  na miejscu. Identyfikator zapisu stoi raz, w zdaniu wyniku (etykieta mówi „Zatwierdzono: N”).
- **Pasek zbioru** nie poszerza okna przy dużym zaznaczeniu - licznik skraca się zamiast rozpychać pasek (przy
  powiększeniu ekranu 160% najmniejsza szerokość okna 2053 → 1749 px).
- **Odmowy zapisu kart mówią zdaniami podglądu makra**, w języku interfejsu: „karta już istnieje (użyj set)” jednym
  zdaniem dla FITS i XISF, wystąpienie `[idx]` spoza nagłówka z liczbą wystąpień, zmiana rodzaju wartości, `set`
  bez `idx` na karcie powtórzonej. Dopisanie karty, która już jest, odmawia przed zapisem, bez przebiegu na próżno.
- **Wydanie obiektu - odmowa manifestu** (uszkodzony, innego wydania, zajęty): otwarte okno wydania mówi, który
  przycisk nacisnąć; po zamknięciu okna pasek podaje ścieżkę manifestu bez rad o przyciskach okna, którego już nie
  ma; przy zajętym pliku roboczym szczegół wskazuje ten plik. Polecenie `project` dopisuje wiersz `potem:`
  z krokiem w terminalu.
- **Esc w czasie zapisu manifestu:** panel raportu dopisuje, że okno zamknie się samo po zakończeniu zapisu.
- **Żniwa:** wydanie, którego wyników WBPP jeszcze nie zapisał, mówi to wprost („folderu wyjścia nie ma”) zamiast
  zgłaszać błąd; przycisk „Wciągnij” jest wyróżniony tylko wtedy, gdy jest co wciągnąć.
- **Błąd programu** w szufladzie zmian, w oknach kart i w planerze (brak stanowiska) kończy się miejscem w kodzie.
- **Błędy Windows** podają kod błędu i ścieżkę jednym zdaniem także w skanie (korzeń archiwum).
- Angielskie komunikaty używają angielskich cudzysłowów zamiast polskich.

## [0.18.0] - 2026-10-18

Wydanie o **zaznaczeniu bez czekania i zapisie, który niczego nie gubi po cichu**. Gdy w systemie działa klient
dostępności (czytnik ekranu albo inny program korzystający z UI Automation), Ctrl+A na całym archiwum trwał kilka
sekund - teraz ułamek sekundy, a zaznaczenie przeżywa sortowanie, grupowanie i podgląd przy każdej wielkości.
Szuflada zmian w Zbiorach zapisuje karty nagłówka w miejscu, jak okna kart. Manifest wydania obiektu -
nieczytelny, uszkodzony albo należący do innego wydania - nigdy nie jest nadpisany po cichu. **Schemat bazy bez
zmian (45):** bazę otwartą w tej wersji dalej otworzy 0.17.0.

### Dodane

- **Przegląd śladów cofnięcia w Porządkach:** ślady cofnięcia zapisu bez werdyktu sprawdzają się w tle przy
  otwarciu Porządków - okno nie czeka, a zamknięcie i zmiana bazy nie blokują; przy awarii sprawdzenia wiersz
  ma przycisk „Ponów sprawdzenie”.
- **„Kopiuj zdanie”** w menu prawego kliku na każdym polu z komunikatem.
- Szczegół błędu programu kończy się miejscem w kodzie (`@ horreum/<plik>.py:<linia>`), bez ścieżek z dysku.

### Zmienione

- **Zaznaczenie w Zbiorach** przy aktywnym kliencie dostępności (archiwum ~17 000 klatek): Ctrl+A ~2,5 s → ~0,2 s,
  klik przy pełnym zaznaczeniu ~2,5 s → ~0,1 s, podgląd zmian ~2,5-3 s → ~0,3 s. Zaznaczenie przeżywa sort,
  grupowanie, podgląd i przeładowanie tego samego zbioru przy każdej wielkości; zdanie „zaznaczenie zdjęte”
  znika. Czytnik ekranu dostaje te same zdarzenia co dotąd.
- **Szuflada zmian zapisuje karty w miejscu**, jak okna kart; gdy plik trzeba przepisać w całości, zdanie wyniku
  to mówi. Klatki wydane dowiązaniem do folderu roboczego WBPP widzą poprawkę.
- **Manifest wydania nigdy nie jest nadpisany po cichu:** gdy jest nieczytelny, uszkodzony albo należy do innego
  wydania, wydanie (także z wiersza poleceń) i naprawa manifestu odmawiają z powodem; wydanie z takim manifestem
  zostaje na liście żniw ze stanem i bez podpowiedzi, że folder można skasować.
- **Naprawa manifestu** stosuje te same reguły co wydanie; gdy czas wydania jest nieznany, bierze go z czasu
  założenia folderu zestawu i oznacza „≈” - data jest orientacyjna i nie rozstrzyga stanu „czeka na WBPP”.
- **Okno wydania:** Esc zamyka okno także w czasie zapisu manifestu; oferta zapisu podaje liczbę dopisywanych
  plików.
- **Pasek stanu:** raport ze szczegółem błędu nie gaśnie po kilku sekundach i zostaje przy swoim ekranie; wynik
  „Napraw nagłówek…” i „Zatwierdź ze ścieżki…” zostaje na pasku po zamknięciu okna razem z poleceniem cofnięcia
  (`horreum header-fix "<baza>" --undo <commit>`).
- Dopisanie karty makrem (`add`) w pliku, który już ma tę kartę, odmawia z powodem („użyj set”).
- Błędy Windows przy zapisie kart i przy zapisie raportu podają ścieżkę pliku.
- Import z fitsmirror przy nieprzeczytanym katalogu mówi, czego nie przeczytał, zamiast podejrzewać wielkość
  liter albo katalog wykluczony.

### Naprawione

- Pole komunikatu pokazuje wartości w kształcie znaczników HTML dosłownie.

## [0.17.0] - 2026-10-18

Wydanie o **zerwanym udziale, który znaczy „nie wiem”, i cofnięciu, które zostawia pliki do oka**. Gdy dysk
sieciowy zniknie w trakcie skanu, sprawdzania kopii albo żniw, program nie uznaje plików za skasowane - mówi,
czego nie przeczytał, i niczego nie zapisuje. Przerwane cofnięcie zapisu kart zostawiało obok pliku kopie,
o których ponowienie milczało; teraz każda trafia do Porządków. Manifest wydania obiektu da się zapisać
ponownie z okna wydania. **Schemat bazy 44 → 45** (werdykt plików przy śladzie cofnięcia): bazę otwartą w tej
wersji 0.16.0 już nie otworzy - przed pierwszym uruchomieniem zrób kopię pliku bazy.

### Dodane

- **Werdykt plików przy śladzie cofnięcia** (migracja 0045): kopia zostawiona obok pliku przez przerwane
  cofnięcie zapisu atomowego trafia do Porządków „Kopie zostawione do oka”, a kolejny zapis tej klatki raz
  odmawia z powodem. Program niczego nie kasuje ani nie przenosi - pliki porównujesz i usuwasz sam; nazwa
  znika z listy dopiero przy dowiedzionym braku pliku.
- **„Zapisz manifest” w oknie wydania:** manifest uszkodzony albo niezapisany po awarii zapisuje się ponownie
  bez ponownego wydania - program sam sprawdza komplet plików wydania i nie gubi niczego z poprzedniego
  manifestu; po awarii kroku manifestu okno od razu pokazuje wynik świeżego sprawdzenia.
- Cofnięcie z kopii tekstowej nagłówka po skanie rozpoznaje plik już cofnięty i mówi, na czym opiera ten
  dowód (`header-fix --undo` podaje to osobnym wierszem).

### Zmienione

- **Zerwany udział sieciowy to „nie wiem”, nie „nie ma”:** skan, obecność kopii i fakty kopii uznają plik za
  zniknięty wyłącznie przy dowiedzionym braku; przy zerwanym udziale niczego nie zapisują, a raport `presence`
  wymienia ścieżki nierozstrzygnięte. Polecenia `scan`, `stacks` i `presence` przy niedostępnym korzeniu
  kończą się jednym wierszem z klasą błędu (kod 1), import z fitsmirror tak samo.
- **Żniwa:** katalogi, których nie dało się przeczytać, są wymienione w planie i na liście wydań; plan niepełny
  nie oznacza wydania jako „wciągnięte” i nie podpowiada, że folder wydania można skasować.
- **Odmowy w oknach** planera, wydania obiektu i zmiany obiektu: odmowa z powodem mówi swoim zdaniem, błąd
  systemu albo bazy - klasą, a błąd nieprzewidziany - „błąd programu” ze szczegółem technicznym pod kursorem.
- **Pasek stanu** Zbiorów, osi obiektu, Dostawy i planera ma szczegół błędu w podpowiedzi i menu „Kopiuj
  zdanie / Kopiuj szczegół”; awaria etapu Dostawy nazywa etap; żniwa i „Zatwierdź ze ścieżki…” zostawiają
  szczegół na pasku po zamknięciu okna; długa ścieżka w zdaniu łamie się w kilku wierszach.
- **Szuflada zmian:** po zapisie przerwanym przez „Anuluj” podgląd pokazuje pozostałe zmiany; zdania bez
  technicznych przedrostków („Writeback:”, „Undo:”, „Rename:”) i z odmianą liczby zmian.
- „Rodowód do potwierdzenia” otwiera się na pierwszym obrazie z panelem Rodowód.
- Okno żniw: pole i przyciski pod listą wydań nie skaczą przy zmianie zdania.

### Naprawione

- Komunikaty wyrażeń filtra i makra z polskimi znakami.

## [0.16.0] - 2026-10-16

Wydanie o **błędach mówionych jednym zdaniem i cofaniu zapisu ze śladem w bazie**. Awaria dysku sieciowego albo
bazy - przy zapisie kart, w Dostawie, na Domu, w planerze, w Porządkach i w wydaniu obiektu - mówi krótkim
zdaniem w języku interfejsu, a surowy komunikat systemu jest pod kursorem (z prawym klikiem „Kopiuj szczegół”).
Cofnięcie zapisu kart drogą atomową zostawia trwały ślad w bazie, więc ponowienie rozpoznaje własny wynik.
**Schemat bazy 43 → 44** (nowa tabela `atomic_undo`): bazę otwartą w tej wersji 0.15.0 już nie otworzy -
przed pierwszym uruchomieniem zrób kopię pliku bazy.

### Dodane

- **Ślad cofnięcia zapisu atomowego** (migracja 0044): wynik cofnięcia utrwalony przed podmianą pliku;
  ponowienie po przerwanym albo padniętym cofnięciu domyka je z dowodem, „już cofnięte” bez ponownego
  czytania pliku; pierwsze cofnięcie nazywa zmianę pliku poza nagłówkiem od zapisu.
- **Klasa błędu bazy:** baza zajęta, niedostępna, pełna albo uszkodzona - zdanie w języku interfejsu
  z nazwą błędu SQLite, w każdym oknie i druku.
- **Pole zdania ze szczegółem:** glif ⓘ przy szczególe, prawy klik „Kopiuj zdanie / Kopiuj szczegół”, pole nie
  rozpycha okna od długiej ścieżki.
- „Rodowód do potwierdzenia”: gest w panelu przechodzi na następny obraz kolejki.

### Zmienione

- Błędy systemu przy wydaniu obiektu, kopii mastera, żniwach, wersjach stosów, kopii wiodącej, w Dostawie,
  na Domu, w planerze i w druku poleceń mówią klasą (odmowa dostępu, brak pliku, brak miejsca, zerwany
  udział); wydanie z błędem kroku podaje, co zostało na dysku, a polecenie `project` kończy się kodem 1 bez
  śladu stosu; manifest wydania zapisywany atomowo.
- Interfejs angielski: powody pominięć w podglądzie zmiany nazw, błędy makra, odmowy w oknach zmiany obiektu
  i wydania, etykieta celu panelu nazw i okna kart bez polskich zdań.
- Zbiory: zaznaczenie przeżywa sortowanie, „Grupuj wg” i podgląd; „Wyczyść podgląd” przy zaznaczeniu całego
  archiwum bez kilkusekundowego odtwarzania; kolumna podglądu znika zaraz po zapisie; Ctrl+A na dużym
  archiwum kilka razy szybciej.
- „Odrzuć nowsze niż obraz we wszystkich obrazach” jednym gestem z menu perspektywy, z „Cofnij werdykt”.
- Okno żniw: pole archiwum i przyciski stoją po dojściu listy wydań (także przy dużym foncie), okno rośnie
  w lewo; brak folderu wyjścia odróżniony od zerwanego udziału.
- Porządki: lista bez rosnącej podłogi okna; trwały błąd bazy przy liczeniu mówi wierszem nad listą.

### Naprawione

- Cofnięcie uwag w Znajdź jednym kliknięciem, także gdy klatka wypadła z widoku.

## [0.15.0] - 2026-10-16

Wydanie o **uzgadnianiu kart z folderem i rodowodzie bez klatek spoza czasu obrazu**. „Uzgodnij” z wiersza
Porządków „Plik nie zgadza się z obiektem” dopisuje kartę `OBJECT` także klatkom obiektu rozpoznawanego po
współrzędnych (np. Veil) i wariantom stosów (autocrop), które wcześniej wypadały z gestu. Wejścia rodowodu
nagrane po zapisaniu obrazu dostają własny wiersz Porządków i przycisk „Odrzuć nowsze niż obraz”. Zaznaczenie
w Zbiorach przeżywa przeładowania widoku, które nie zmieniają zbioru. Schemat bazy bez zmian (wersja 43) -
bazę otwartą w tej wersji dalej otworzy 0.14.0.

### Dodane

- **Forma karty obiektu-regionu:** obiekt rozpoznawany po współrzędnych dostaje formę karty `OBJECT` zgodną
  z plikami w jego folderze, więc „Uzgodnij” i „Zmień obiekt…” piszą kartę także klatkom, które region
  sprowadza z powrotem do obiektu; klatka spoza regionu dostaje odmowę z powodem.
- **Rodowód z klatkami nowszymi niż obraz:** wiersz Porządków i perspektywa w Zbiorach, przycisk „Odrzuć
  nowsze niż obraz” w panelu Rodowód (z „Cofnij werdykt”) oraz stan „tylko klatki nowsze niż obraz” w kolumnie
  i facecie Rodowód.
- „Uzgodnij” podaje sumę dróg zapisu kart (w miejscu / cały plik / zależy od pliku), a klatki z kilkoma
  kopiami pomija z receptą wspólną z wierszem „Duplikaty”.

### Zmienione

- „Uzgodnij” zapisuje kartę wariantom stosów (autocrop), gdy oryginał jest bez zmian - warianty nie są już
  zdejmowane jako para; wiersz „Plik nie zgadza się z obiektem” sprawdza każdą obecną kopię.
- Błędy systemu przy zapisie kart (odmowa dostępu, brak pliku, brak miejsca, zerwany udział sieciowy) mówią
  krótkim zdaniem w języku interfejsu; surowy komunikat systemu jest w podpowiedzi.
- Pliki FITS z sumą kontrolną (`CHECKSUM`, `DATASUM`): obie drogi zapisu odmawiają jedną regułą.
- Cofnięcie zapisu w miejscu uznaje plik za „już cofnięty” wyłącznie z dowodem całego pliku; przerwane
  cofnięcie mówi, ile plików wymaga sprawdzenia, bez obietnicy wyniku.
- Zaznaczenie w Zbiorach przeżywa przeładowania, które nie zmieniają zbioru (wynik Pól, kolumny wybrane ręką,
  Dostawa, grupowanie po wersji stosu, kolumna „Wersja”); panel Rodowód zachowuje noc, relację i wiersze.
- Szuflada Zbiorów podaje pozostałe powody w podpowiedzi; status „Napraw nagłówek…” nie ucina zdania.

### Naprawione

- Cel gestu bez klatki w bieżącym zbiorze nie nadpisuje już zaznaczenia zrobionego ręką.

## [0.14.0] - 2026-10-16

Wydanie o **karcie FITS dopisanej w miejscu i powodach zapisu w języku interfejsu**. „Zmień obiekt…”
dopisuje brakującą kartę `OBJECT` do pliku FITS bez przepisywania całego pliku, więc dowiązania twarde
w wydaniach do WBPP widzą zmianę od razu, a okno jeszcze przed zapisem mówi przy każdej pozycji, którą
drogą pójdzie karta. Powody zapisu, blokad i cofnięcia mówią w języku interfejsu. Propozycja rodowodu
stosu nie podsuwa klatek nagranych po powstaniu obrazu. Schemat bazy rośnie z wersji 41 do 43.

Bazy otwartej w tej wersji nie otworzysz już w 0.13.0 - tamto wydanie odmówi bazy z nowszego
schematu. Przed pierwszym otwarciem zrób kopię bazy, jeśli chcesz zachować drogę powrotu.

### Dodane

- **Dopisanie karty FITS w miejscu:** gdy plik FITS nie ma karty `OBJECT`, a za `END` jest wolny rekord,
  „Zmień obiekt…” dopisuje kartę w miejscu - w tym samym położeniu i kolejności, jakie dałby pełny zapis.
  Bez wolnego miejsca karta idzie zapisem całego pliku z powodem przy pozycji. Cofnięcie oddaje plik bajt
  w bajt.
- **Prognoza drogi zapisu** w oknie „Zmień obiekt…”: przy każdej pozycji „w miejscu”, „cały plik” albo
  „zależy od pliku”, a pod listą jedno zdanie wyjaśnienia.
- **Rodowód stosu bez klatek nowszych niż obraz:** propozycja pomija klatki nagrane po zapisaniu stosu,
  a panel Rodowód mówi „Pominiętych N klatek nowszych niż obraz” - także poza trybem propozycji.

### Zmienione

- Powody zapisu kart i zmiany nazw, odmowy czytnika XISF i naruszenia reguł karty mówią w języku
  interfejsu - wersja angielska nie pokazuje w oknach zapisu polskich zdań.
- Okna kart: „Cofnij” znika dopiero po cofnięciu domkniętym, a przy blokadzie albo przerwaniu zostaje
  z powodem; wynik osobno liczy pozycje „już cofnięte”. Blokady z różnych powodów: zdanie podaje
  „pierwszy z N różnych powodów”, pozostałe są w podpowiedzi.
- „Napraw nagłówek…” i „Zatwierdź ze ścieżki…” pomijają pliki FITS z sumą kontrolną (`CHECKSUM`,
  `DATASUM`) już w podglądzie i wskazują ich folder; licznik przycisku ich nie liczy.
- Kubełek „Rodowód do potwierdzenia” w Porządkach nie trzyma stosów, którym zostały wyłącznie klatki
  nowsze niż obraz.
- Planer: jedna reguła „ta nazwa to ten cel” dla szukania i planu; `horreum plan --find` mówi, gdy cel
  chowają filtry, a najbliżsi kandydaci idą po pewności dopasowania.
- Schemat bazy v43: wersja 42 zapisuje powody pozycji zapisu kodem, wersja 43 dokłada indeks klatek
  po obiekcie. Migracje wjeżdżają same przy pierwszym otwarciu i nie ruszają klatek ani kopii.

### Naprawione

- Po cofnięciu w oknach kart przycisk zapisu nie wracał od razu do aktywnego.
- Zaznaczenie w Zbiorach zaraz po wejściu ginęło przy przeładowaniu Pól.

## [0.13.0] - 2026-10-15

Wydanie o **gestach, które cofasz bez śladu, i planerze, który zna nazwy katalogowe**. Cofnięcie
„Zmień obiekt…” zdejmuje także obiekt, który ten gest założył, a teleskop dopisany przez „Dopisz
nowy…” cofniesz jednym przyciskiem, również po ponownym uruchomieniu programu. Planer i Porządki znają
pełną tabelę Messiera, katalog Arp i mgławice planetarne z oznaczeniem pewności, a szukanie celu stawia
trafienie dokładne na górze listy. Schemat bazy rośnie z wersji 39 do 41.

Bazy otwartej w tej wersji nie otworzysz już w 0.12.0 - tamto wydanie odmówi bazy z nowszego
schematu. Przed pierwszym otwarciem zrób kopię bazy, jeśli chcesz zachować drogę powrotu.

### Dodane

- **Cofnij dopisanie** na Osi teleskopu: teleskop dopisany przez „Dopisz nowy…” cofniesz przyciskiem
  przy nim albo receptą z paska stanu. Ślad gestu zostaje w bazie, więc przycisk przeżywa zmianę strony
  i restart programu.
- **Porządki: „Nazwa katalogowa wskazuje inny obiekt”** - klatki, których nazwa katalogowa (na przykład
  numer Messiera) prowadzi do innego obiektu niż ten, do którego są przypisane; wiersz otwiera je
  w Zbiorach. Raport Dostawy dopisuje człony „nazwa katalogowa przepięta” i „wskazuje inny obiekt”,
  a przy zerze milczy.
- **Katalogi:** pełna tabela Messier → NGC/IC (106 par, VizieR VII/118), nazwy z katalogu Arp (54)
  i 131 mgławic planetarnych z oznaczeniem statusu: potwierdzona, kandydatka albo mimika (na przykład
  „SNR (mimika PN)”). Katalog celów planera rośnie z 1559 do 1691 pozycji.
- **Planer: przełącznik „Ukryj kandydatki i mimiki PN”** - domyślnie wyłączony; pasek mówi, ile celów
  schował.
- **Gotowe obrazy bez oryginału** (wiersz poleceń, `horreum stack-versions --standalone`): autocropy,
  których oryginału nie ma w archiwum, trafiają do archiwum stosów pod obiekt, zestaw i filtr z karty
  pliku; bliźniacze nazwy dostają przyrostek `_2`, a plik już obecny w archiwum zostaje rozpoznany.

### Zmienione

- **Szukanie celu w planerze** zna formy katalogowe i nazwy potoczne: „M 27”, „m27” i „Arp 244”
  trafiają swój cel, a trafienie dokładne stoi przed trafieniami po fragmencie nazwy. Pusty wynik mówi
  dlaczego: nazwa znana, ale spoza celów planera („M 13” → „= NGC6205, poza celami planera”), cel
  z innej warstwy albo cel schowany przez bieżące filtry.
- Powody pozycji w oknie przebiegu „Zmień obiekt…”, ostrzeżenia planu zmiany obiektu i szczegóły
  pominięć mówią w języku interfejsu - wersja angielska nie pokazuje w tych oknach polskich zdań.
  Szczegół z warstwy zapisu karty jest jeszcze po polsku.
- Okno żniw przy niepodłączonym dysku karty mówi „Folder karty nie istnieje: …” zamiast „na kartach nie
  ma jeszcze wydań”. Długa ścieżka w zdaniu okna nie poszerza go; pełną widać w podpowiedzi.
- Zestawy pomijają klatki zastąpione i wycofane, więc log grupowania liczy to samo co Porządki.
- Kontrola `horreum human-facts --baseline` pilnuje także aliasów nazw nadanych ręką.
- Schemat bazy v41: wersja 40 dokłada nagrobki obiektów i teleskopów założonych gestem, który cofnięto
  (listy i wiersz poleceń ich nie pokazują), oraz ślad gestu „Dopisz nowy…”; wersja 41 zapisuje powody
  pozycji zmiany obiektu kodem. Migracje wjeżdżają same przy pierwszym otwarciu i nie ruszają klatek
  ani kopii.

### Naprawione

- Cofnięcie „Zmień obiekt…” z nową nazwą zostawiało obiekt bez klatek na liście „Istniejący obiekt”
  i w „ostatnio użytych”.

## [0.12.0] - 2026-10-14

Wydanie o **teleskopie, który zna swoją optykę, i oknie, które nie stoi**. Ogniskową i f/ teleskopu
poprawisz teraz ręką na Osi teleskopu, a Porządki wskażą klatki, których optyka nie pasuje do
teleskopu. Gesty w Zbiorach, koniec Dostawy i wejście w Porządki nie zamrażają już okna, a pasek stanu
trzyma raport gestu i jego „Cofnij” obok siebie. Zapis do plików jest ostrożniejszy: Horreum nie
melduje sukcesu bez dowodu, a podmiana pliku przerwana w połowie (awaria, wyłączenie komputera, inny
program piszący ten sam plik) daje się dokończyć bez utraty żadnej wersji. Do tego szlif słów
w obu językach. Schemat bazy rośnie z wersji 36 do 39.

Bazy otwartej w tej wersji nie otworzysz już w 0.11.0 - tamto wydanie odmówi bazy z nowszego
schematu. Przed pierwszym otwarciem zrób kopię bazy, jeśli chcesz zachować drogę powrotu.

### Dodane

- **Ogniskowa i f/ teleskopu wpisane ręką.** Dwuklik w kolumnach **f/** i **Ogniskowa** na Osi
  teleskopu zapisuje Twoją wartość. Pliki zostają bez zmian. Twoja wartość wygrywa w osi, planerze
  i Porządkach, a obok dalej widać, co mówią pliki. **Przywróć z plików** ją zdejmuje.
- **Panel Zestawy** na Osi teleskopu: piksel, skala ″/px przy bin 1 i bin 2 i kadr dla każdej
  kamery, a nad nimi średnica wyliczona z ogniskowej i f/.
- **Porządki: „Ogniskowa niezgodna z teleskopem"** - wybierasz teleskop z listy tych o pasującej
  ogniskowej (5 %) albo dopisujesz nowy razem z parkiem. Horreum nigdy nie zakłada teleskopu sam.
- **Porządki: „f/ niezgodna z teleskopem"** - perspektywa z kolumną FOCRATIO i gestem **Popraw f/
  w plikach…** przez szufladę zapisu, z cofnięciem. Gest poprawia tylko mniejszość plików. Gdy f/
  teleskopu nie zgadza się z większością jego plików, odmawia i mówi dlaczego.
- **Porządki: „Zeznanie wstrzymane” i „Kopie zostawione do oka”.** Gdy karta trafiła do pliku, ale
  baza nie mogła jeszcze potwierdzić, co plik teraz mówi (druga kopia tej samej klatki wjechała
  w trakcie zapisu), zapis nie melduje sukcesu, tylko „plik zapisany, zeznanie wstrzymane”, a wiersz
  Porządków prowadzi do gestu „Ta kopia prowadzi”. Gdy podmiana pliku spotkała obcą wersję albo
  przerwała się w połowie, żadna wersja nie znika - zostawione kopie czekają w Porządkach na Twoje oko.
- **Dostawa mówi, których katalogów nie przeczytała** - przebieg niekompletny wymienia je z nazwy
  i ma przycisk **Skanuj ponownie** na tych samych ustawieniach. Wiersz „czeka na Ciebie N” prowadzi
  prosto do listy, a log przebiegu po Twoim geście dostaje podpis „Przebieg z HH:MM (stan sprzed
  Twoich zmian)”.
- **Znajdź zna numery Messiera** obiektów z archiwum: „M64” trafia NGC4826, tak samo M27, M33, M63,
  M65, M78 i M94.
- **Wróć do archiwum bazy** w oknie żniw - po zmianie archiwum jednym przyciskiem wracasz do
  archiwum, które zna baza.

### Zmienione

- Ogniskowa i f/ teleskopu to wartość najczęstsza wśród klatek. Liczy się od nowa przy pierwszym
  otwarciu bazy w tej wersji, przy każdym **Przyjmij** i po każdym przypięciu klatek do teleskopu.
  Dotąd zapisywała się z pierwszej klatki i już się nie zmieniała - A140R pokazywał f/8.0 przy
  7370 klatkach f/5.6. Komórka, która nie zgadza się z plikami, mówi „nieaktualne”.
- Planer liczy kadr z ogniskowej teleskopu: najpierw Twojej, potem z plików. Zestawy teleskopu
  scalonego są widoczne pod teleskopem, w który go scalono.
- Schemat bazy v39: kolumny ręki optyki teleskopu. Teleskop dopisany kiedyś ręką przenosi swoją
  ogniskową do nowej kolumny. Wersje 37 i 38 dokładają stan wstrzymanych zapisów i zamiar podmiany
  pliku; migracje wjeżdżają same przy pierwszym otwarciu i nie ruszają klatek ani kopii.
- **Pasek stanu:** raport gestu stoi we własnym polu, a przycisk „Cofnij” zaraz za nim; faza
  przebiegu przesunęła się do prawej krawędzi. Przez 5 s komunikaty etapów Dostawy nie zagłuszają
  raportu. Dom → „Ostatnio” opisuje ten sam gest co pasek, w klatkach.
- **Okno nie stoi po geście.** Gesty w Zbiorach („Cofnij przypisanie” i pozostałe zapisy) składają
  zbiór w tle: przestój spadł z 2-4 s do ok. 0,1 s. W trakcie składu klik nie zmienia zaznaczenia,
  a menu i drugi gest odmawiają z powodem. Koniec przebiegu Dostawy stoi ok. 0,4 s zamiast 2-3 s,
  wejście w Porządki bez zmian w bazie jest natychmiastowe.
- **Wciągnij z WBPP…** przeszło do menu „Więcej…” na Domu; po „Zamknij i przyjmij” program przechodzi
  na Dostawę. Przycisk „Przyjmij nowe (…)” wymienia etapy tymi samymi słowami co log.
- **Wskaż stanowisko… (N)** nie liczy już darków i biasów - nie mają teleskopu, więc wypadły
  z listy. Jedno trafienie w szukajce okna przypisania jest od razu zaznaczone, Enter zatwierdza.
- **Zmień obiekt…:** fraza bez trafień przechodzi do pola nazwy, a przycisk mówi „Załóż … i przypisz” -
  nowy obiekt powstaje dopiero po Enterze w polu nazwy. Lista podglądu przy wąskim oknie zostawia
  widoczny folder obiektu. Powody pominięć i błędy plików mówią po ludzku, bez surowych komunikatów
  systemu w rodzaju `[WinError 32]`.
- Godziny poniżej 6 minut pokazują się w minutach („< 1 min”, „4 min”) w bibliotece, na Domu
  i w planerze. Kolumny liczb mają jedną precyzję na kolumnę. Wzór nazwy zwija się po pierwszym użyciu.
- Planer liczy kadr szerokich obiektywów kątem (48 mm: 41,1° zamiast 43,0°); przy teleskopach
  różnica jest niezauważalna.
- Nazwa obiektu w podpowiedzi listwy facetów brzmi tak samo jak w oknie przypisania (`Cr464`, nie
  `COLLINDER464`).
- Wersja angielska ma mniej polskich słów i polskich cudzysłowów w oknach wydania, żniw i przypisania;
  poprawiona odmiana liczebników („1 klatka”, nie „1 klatek”) w zdaniach wyniku.

### Naprawione

- Zamknięcie „Zmień obiekt…” albo „Uzgodnij pliki…” w trakcie liczenia planu mogło wywrócić program.
- Enter w szukajce okna przypisania potrafił założyć nowy obiekt i przypisać mu klatki bez Twojej
  decyzji; Enter w „Napraw nagłówek…” i „Zatwierdź ze ścieżki…” nie zapisuje już kart do plików.
- Menu kontekstowe i „Zostaw tę wersję” w trakcie wczytywania zbioru działały na poprzednim
  zaznaczeniu.
- Procenty teczki sumują się do pokrycia: Cr464 pokazuje 79 + 21, nie 79 + 20.
- Okno wydania nie rośnie od długiej ścieżki wyjścia WBPP.
- Grupowanie nie dopisuje już setek zdarzeń przy każdym przebiegu Dostawy.

## [0.11.0] - 2026-10-12

Wydanie o **całej drodze jednego obiektu** - od nocy na dysku do gotowego stosu w archiwum. Dotąd
Horreum był przede wszystkim katalogiem: materiał do obróbki składałeś z perspektyw, a wyniki WBPP
przenosiłeś do archiwum sam. Teraz program startuje na ekranie Dom z czterema drogami: **Przyjmij**
wpuszcza nową noc i mówi, co przyszło i czego nie rozpoznał; **Znajdź** jednym polem pokazuje klatki
obiektu, nocy, filtra albo Twojej uwagi; **Wydaj do WBPP** układa komplet obiektu - lighty, mastery
i surowe flaty - jako linki w folderze roboczym; **Popraw** prowadzi do zadań, których automat nie był
pewny. Po obróbce **Wciągnij z WBPP…** kopiuje nowe mastery flat i stosy do archiwum pod porządną
nazwą i z dokładnym rodowodem. Program ostrożniej pisze też do plików: kartę `OBJECT` podmienia
w miejscu, pod blokadą i z kopią nagłówka, a gest **Zmień obiekt…** przenosi plik do folderu obiektu
razem z kartą, z jednym cofnięciem. Schemat bazy rośnie z wersji 19 do 36 - migracje wjeżdżają same
przy pierwszym otwarciu i nie ruszają klatek ani kopii; jedyna przebudowa przepisuje zapis powiązań
stosów z klatkami. Dłużej potrwa pierwsze **Przyjmij** po aktualizacji: raz doczyta nagłówki plików
XISF, klatek leżących w kilku kopiach i stosów.

Bazy otwartej w tej wersji nie otwieraj już w 0.10.0 ani starszej: dopiero od tego wydania Horreum
odmawia bazy z nowszego schematu, a starsze wydania otworzą ją bez słowa.

### Dodane

- **Przyjmij - po nocy widzisz, co przyszło, i od razu nazywasz to, czego program nie rozpoznał.**
  Kafel „Przyjmij” na Domu uruchamia przyjęcie jednym kliknięciem (za pierwszym razem pyta
  o katalog archiwum), a nad przyciskami Dostawy staje panel „Co przyszło”: nowe klatki według
  rodzaju, kopie znanych klatek, obiekty z godzinami i czym skalibrujesz nowe lighty. Pod
  „Nie rozpoznałem: N” każda nierozpoznana nazwa z nagłówka ma przycisk „Przypisz obiekt…”; po
  zapisie pasek mówi „Zapamiętałem: … - następne dostawy rozpoznają same”. Kubełki bez nazwy
  prowadzą prosto do swojej naprawy w Porządkach, a przebieg, który nie ruszył albo przerwał się
  w połowie, mówi to wprost zamiast udawać pustą dostawę.

- **Znajdź - jedno pole zamiast przeklikiwania filtrów.** Wpisujesz nazwę obiektu (potoczną albo
  katalogową) i warunki `noc:2026-08`, `filtr:Ha,OIII`, `teleskop:`, `zestaw:`, `uwagi:` (działają też
  angielskie `night:`, `filter:`, `telescope:`, `setup:`, `notes:`), Enter - i masz klatki w tabeli
  z prostym zestawem kolumn. Każdy warunek staje się chipem nad tabelą, który zdejmiesz jednym
  kliknięciem, a część zapytania nieznaną archiwum program nazywa („Nie znam: … - reszta zapytania
  działa.”). Pod tabelą stoi pasek czasowników na zaznaczeniu: „Wydaj do WBPP”, „Popraw nagłówki…”,
  „Obiekt”, „Rodowód…”, „Uwagi…”, „Kolumny” i „Zbiory klasyczne”, który niesie ten sam zbiór do
  pełnego widoku.

- **Wydaj do WBPP - komplet obiektu na stół jednym gestem.** Kafel „Wydaj do WBPP” (w Zbiorach
  klasycznych „Wydaj obiekt…”) otwiera listę obiektów z gotowością kalibracji: godziny, noce,
  zestawy, procent lightów z master flatem, surowym flatem i darkiem oraz kropkę stanu. Wybrany
  obiekt wyjeżdża do `OBJECTS\<obiekt>` w folderze roboczym: lighty, mastery z kalibracji i - gdzie
  mastera flat brak - surowe flaty tej samej nastawy z najbliższej nocy w oknie 30 dni, w drzewie
  rozdzielonym zestawem (teleskop i kamera), bo WBPP grupuje po filtrze i ekspozycji, a nie po
  optyce. Podgląd liczy się sam i podaje braki z powodem; gdy folder roboczy leży na dysku archiwum,
  wydanie to linki, które nie zajmują miejsca, a ponowne wydanie dokłada tylko to, czego na stole
  brakuje. Folder roboczy wskazujesz raz („Plik → Folder roboczy WBPP…”), a po wydaniu wiersz
  „Wyjście WBPP:” z przyciskiem „Kopiuj ścieżkę” podaje folder `out` dla WBPP.

- **Wciągnij z WBPP… - nowe mastery i stosy wracają do archiwum z rodowodem.** W sekcji „Stosy”
  Dostawy okno „Wciągnij wyniki WBPP” pokazuje listę wydań ze stanem („czeka na WBPP”, „do
  wciągnięcia N”, „wciągnięte N”, „do przeglądu N”) i tabelę plików z nazwą i katalogiem docelowym.
  Master flat trafia do `CALIBRATION\masters\flats\<zestaw>\<filtr>`, gdy historia integracji w pliku
  wymienia surowe flaty znane bazie, a stos z wydania Horreum - do `STACKS\<obiekt>\<zestaw>\<filtr>`;
  master dark i bias idą do przeglądu z powodem, bo archiwum nie ma surowych darków, z których
  mogłyby powstać. Program nadaje nazwę z faktów, kopiuje bez nadpisywania i sprawdza bajty kopii,
  a „Zamknij i przyjmij do archiwum” przyjmuje kopie i zapisuje stosom dokładny rodowód - klatki,
  których WBPP naprawdę użył, a nie okno czasu. Gdy obiekt stosu różni się od obiektu wydania, pasek
  proponuje „Przypisz obiekt wydania” z drogą powrotu, a lista wydań mówi, kiedy folder wydania
  możesz już skasować.

- **Zmień obiekt… - obiekt, folder i karta `OBJECT` zmieniają się razem.** W menu „Obiekt” na
  zaznaczeniu nowa pozycja przepina obiekt w bazie, przenosi plik do folderu tego obiektu
  w archiwum i wpisuje kartę `OBJECT` - per plik razem albo wcale. Okno najpierw pokazuje plan
  (ścieżka dziś i po zmianie, karta przed i po, nowe katalogi, puste katalogi do usunięcia,
  pominięte z powodem), a „Cofnij” przywraca karty, pliki, katalogi i obiekt (po zamknięciu okna -
  `horreum object-change undo`). W nazwie pliku zmienia się wyłącznie człon obiektu na początku,
  reszta zostaje znak w znak. Porządki mają wiersz „Plik nie zgadza się z obiektem” z gestem
  „Uzgodnij pliki…” (obiekt w bazie zostaje, plik go dogania) oraz „Przerwane zmiany obiektu”,
  który otwiera przerwany przebieg z „Dokończ” i „Cofnij”.

- **Uwagi klatek - Twoje zdanie zostaje przy klatce.** Zaznacz klatki i kliknij „Uwagi…” (w Zbiorach
  klasycznych: menu „Klatka”): jedno krótkie zdanie, do 300 znaków, np. „chmury po 2:00”. Uwaga żyje
  wyłącznie w bazie, nigdy w pliku, i przeżywa każde kolejne przyjęcie. Znajdziesz ją w Znajdź słowem
  z treści albo `uwagi:…`, a pomyłkę cofa „Cofnij uwagi” na pasku stanu albo w wierszu „Ostatnio” na
  Domu.

- **Kopie jednej klatki mówią, czym się różnią, a Ty wskazujesz, która prowadzi.** Gdy ta sama klatka
  leży w kilku miejscach, Horreum zapisuje zeznanie nagłówka każdej kopii i - dla XISF - liczbę i role
  obrazów w pliku. Kolumna „Obrazy” (w perspektywach kopii, do włączenia w „Polach”) i podpowiedź
  „×N” pokazują, w czym kopie mówią inaczej, także grupę flatów, filtr w nazwie i folder filtra.
  Porządki mają wiersze „Klatki z niezgodnymi kopiami” i „Zeznanie z nieobecnej kopii” (klatka mówi
  głosem pliku, którego już nie ma); prawy klik → „Ta kopia prowadzi” wskazuje kopię, której nagłówek
  ma mówić za klatkę, i Dostawa tego wyboru nie przestawi. Klatkę z jedną ocalałą kopią Dostawa
  naprawia sama - czyta plik, sprawdza, że to te same dane, i przejmuje jego zeznanie - a fakty kopii
  bez pełnego skanu zbiera przycisk „Zbierz fakty kopii (N)”.

- **Rodowód widać w tabeli, a kalibrator klatki wskażesz ręką.** Kolumna i filtr „Rodowód” mówią
  przy każdym gotowym obrazie, na czym stoi jego rodowód (dokładny, z historii pliku, częściowo
  potwierdzony, z okna czasu, do potwierdzenia), a perspektywa „Gotowe obrazy” pokazuje stosy
  pogrupowane według tego stanu. Dwuklik wiersza w panelu „Rodowód…” pokazuje te klatki w tabeli,
  a werdykt wejść stosu cofa „Cofnij werdykt”. Dla klatki nieba panel ma „Wskaż kalibrator…”:
  master dark albo flat wybierzesz także spoza przepisu - program nazywa wtedy niezgodność (filtr,
  teleskop, binning, ekspozycja, temperatura, gain, offset) - a wybór przetrwa przeliczenia;
  „Przywróć automat” oddaje decyzję programowi.

- **Perspektywa „Wersje stosów” - ten sam materiał zintegrowany kilka razy.** Stosy jednego obiektu,
  kamery, filtra, ekspozycji i okna czasu tworzą grupę, a każda para dostaje ocenę z dowodem: inna
  integracja, pochodna tej samej integracji albo nieustalone. Kolumna „Wersja” podaje liczbę obrazów
  w pliku i datę integracji. Prawy klik → „Zostaw tę wersję” kopiuje do schowka ścieżki pozostałych
  wersji, a „Zostaw wszystkie wersje” zapisuje werdykt, który zdejmuje grupę z roboty w Porządkach
  (cofniesz go w tym samym menu). Horreum niczego tu nie kasuje.

- **Stanowisko wskażesz ręką klatkom bez GPS.** Zdjęcia z lustrzanki i inne klatki bez współrzędnych
  w nagłówku dostają stanowisko w oknie „Wskaż stanowisko…” na osi obserwatorium: okno grupuje je po
  folderach, a stanowisko wybierasz z listy albo zakładasz ze współrzędnych (punkt blisko istniejącego
  trafia w nie, bez duplikatu). Wskazanie zmienisz („Zmień wskazanie…”) albo cofniesz („Cofnij
  wskazanie…”), a automat go nie nadpisze. To okno i „Przypisz zestaw…” startują szersze, mają filtr
  listy folderów, długą ścieżkę skracają w środku (licznik zostaje widoczny), a zapis bierze dokładnie
  te zaznaczone foldery, które widać po filtrze.

- **Gotowy stos bez nazwy dostaje propozycję z folderu.** Stos leżący w drzewie
  `STACKS\<obiekt>\<zestaw>\<filtr>`, którego plik nie zapisał obiektu, trafiał do kubełka „bez nazwy,
  gotowe stosy” i każdy kosztował ręczne wpisanie nazwy. Teraz program czyta nazwę z folderu obiektu
  i podaje ją jako propozycję: w Przeglądzie obiektów pod kubełkiem stosów stoi wiersz „…z tego ze
  ścieżki”, a „Zatwierdź ze ścieżki…” nadaje nazwę jednym gestem. Propozycja nigdy nie zapisuje się
  sama, nie powstaje, gdy plik mówi coś o obiekcie albo gdy nazwę zdjąłeś ręką, i milknie, gdy dwie
  kopie tego samego stosu leżą w folderach różnych obiektów; potwierdzonej nazwy nie przepisze
  później dopasowanie po współrzędnych. Dialog „Napraw nagłówek…” grupuje stosy po folderze obiektu,
  a nie po folderze filtra.

- **Stos wie, który to kanał i czy jest tylko skadrowaną wersją innego.** Trzy stosy R, G i B jednej
  integracji kamery kolorowej nie wyglądają już jak trzy kopie tego samego obrazu: kanał z nazwy pliku
  ma własny filtr „Kanał”. „Wciągnij stosy…” bierze też skadrowany wariant `_autocrop` (dotąd pomijany
  jako dalsza obróbka); taki wariant jest osobnym obrazem powiązanym z oryginałem, dziedziczy po nim
  obiekt i zestaw (przy kadrowaniu znikają często karty `TELESCOP` i `OBJECT`) i nie udaje drugiej
  integracji w „Wersjach stosów”.

- **Stos z mieszanym materiałem mówi o RAW-ach, których nie umie umieścić w czasie.** Gdy obraz ma
  już rodowód z plików FITS, a obok leżą zdjęcia z lustrzanki bez znanego zegara, panel rodowodu
  mówi „a tych N nie umiem umieścić w czasie” i podsuwa wskazanie odniesienia - tylko wtedy, gdy
  to wskazanie naprawdę może je wciągnąć.

- **Planer patrzy na kadr i rozumie lustrzanki.** Nowa kolumna „Wypełn.” mówi, jaką część kadru
  wypełnia cel (komórka mozaiki jest przygaszona), a pola „Min. wypełnienie” i „Maks. paneli”
  włączają filtr kadru, który chowa cele, jakich żaden zestaw parku nie zrobi w zadanym wypełnieniu
  albo liczbie paneli - domyślnie wyłączony. Dla zdjęć z lustrzanki planer bierze z EXIF wymiary
  kadru i - gdy plik go podaje - rozmiar piksela; już przyjęte RAW-y potrzebują jednego ponownego
  odczytu (`horreum scan --reread-raw`), a piksel matrycy możesz też wpisać ręką (`horreum camera`).

- **Recepta na pasku stanu da się kliknąć.** Po geście, który da się cofnąć (wycofanie klatki,
  cofnięcie albo przywrócenie przypisania obiektu), pasek nie tylko podpowiada drogę powrotu, ale
  ją wykonuje: klik odsłania klatki poza widokiem, a potem cofa gest - dokładnie na tych klatkach,
  które gest zmienił, nie na całym zaznaczeniu. Po wykonaniu zaznaczone klatki stoją na środku
  tabeli, a nie przy dolnej krawędzi. Recepta żyje tak długo, jak jest prawdą, i nie wykonuje się
  w trakcie etapu Dostawy ani zapisu do plików.

- **Edycja pojedynczej komórki w Zbiorach klasycznych.** Komórkę keyworda (dla klatki z jedną obecną
  kopią, nie RAW-a) edytujesz w miejscu, z polem komentarza jak w makrze. Zmiana trafia do tej samej
  szuflady co makro: widzisz ją w podglądzie razem z innymi oczekującymi kartami tej klatki,
  zatwierdzasz albo odrzucasz i cofasz jak każdy zapis.

- **Porządki pokazują klatki bez zestawu i bez stanowiska.** Dwa nowe wiersze z liczbą prowadzą
  wprost do gestu („Przypisz zestaw…”, „Wskaż stanowisko…”). Nowy wiersz „Fakt ręki zatrzymany na
  zastąpionej klatce” pokazuje, co zostało przy klatce zastąpionej, a w perspektywie „Zastąpione”
  menu tabeli ma gest „Przenieś fakty ręki”.

- **Perspektywa „Wycofane, a plik wrócił”.** Klatka, którą wycofałeś, a której plik znów jest na
  dysku, ma własną listę i własne zdanie w kolumnie „Ścieżka” („wycofana, plik wrócił”) z drogą
  powrotu w podpowiedzi. Dotąd wiersz Porządków prowadził do wszystkich wycofanych naraz i nie dało
  się odróżnić tej jednej od klatek, których pliku naprawdę nie ma.

- **Biblioteka obiektów ma kolumnę „Godziny”.** Suma ekspozycji lightów per obiekt pod bieżącym
  filtrem, z dopiskiem, ile klatek nie ma czasu ekspozycji.

- **Zapisana perspektywa pamięta wygląd.** Wybór kolumny „Obrazy” i szerokość kolumny ścieżki
  wracają z perspektywą; wybór soczewki w planerze przeżywa restart programu.

- **Nowe tokeny we wzorze nazw plików.** Panel „Uporządkuj nazwy plików…” zna token „grupa flatu
  (FLATGRP)” - grupę flatu z mastera, którym klatkę skalibrowano, a `NOFLAT`, gdy go nie ma - oraz
  „końcowe _ (ostatni)”, a token rodzaju klatki ma wybór wielkości liter.

### Zmienione

- **Program startuje na ekranie Dom z czterema drogami.** Po otwarciu bazy widzisz „Co chcesz
  zrobić?” i kafle „Przyjmij”, „Znajdź”, „Wydaj do WBPP” i „Popraw · N” (ta sama liczba co przy
  Porządkach), a pod nimi „Co mam:”, „Teczki - najwięcej godzin” i wiersz „Ostatnio” z przyciskiem,
  który cofa Twój ostatni gest. Teczek jest do osiemnastu, każda z kropką stanu kalibracji; klik
  pokazuje klatki obiektu w Znajdź, a wyższe okno odsłania więcej rzędów bez paska przewijania.
  Pasek boczny ma Dom i Znajdź, a pod „Więcej” dawne strony: Dostawa, Zbiory klasyczne (dawne
  „Zbiory”), Porządki i Planer - nic nie zniknęło, kafle prowadzą tam krótszą drogą. Rzadsze
  narzędzia zbiera przycisk „Więcej…”, a instrukcja obsługi jest przepisana według czterech dróg.

- **Karta `OBJECT` zapisuje się w miejscu, a nie przez przepisanie całego pliku.** „Napraw
  nagłówek…” i „Zatwierdź ze ścieżki…” (który teraz także dopisuje kartę do pliku tam, gdzie plik na
  to pozwala, z przyciskiem „Cofnij karty”) podmieniają samą kartę w nagłówku: plik nie wędruje
  w całości po sieci, a linki do niego, np. w wydaniu dla WBPP, zostają. Na czas zapisu plik jest
  zablokowany dla innych programów, nagłówek ma kopię zapasową sprzed pierwszego bajtu, a po zapisie
  program sprawdza, że dane obrazu są te same; gdy w nagłówku nie ma miejsca (np. FITS bez karty
  `OBJECT`), plik jest przepisany w całości i okno to mówi. Zapis przerwany w połowie odcina plik od
  skanu i trafia do Porządków („Plik po przerwanym zapisie”, „Zapis czeka na dokończenie”) z gestami
  pod prawym klikiem: „Dokończ zapis”, „Przywróć nagłówek sprzed zapisu” i „Zwolnij plik do skanu…”
  (z obowiązkowym powodem).

- **Jedna forma nazwy obiektu w pliku, aliasy na wierzchu.** Do karty `OBJECT` Horreum pisze zawsze
  tę samą formę: oznaczenie katalogowe ze spacją, z numerem NGC tam, gdzie obiekt go ma - folder
  `M82` daje kartę `NGC 3034`, a „Bubble Nebula” - `NGC 7635`; w bazie i w nazwach folderów zostaje
  kanon bez spacji. Dotąd „Napraw nagłówek…” pisał do pliku formę folderu, teraz jest ona tylko
  propozycją w polu edycji. Okno „Przypisz obiekt” pokazuje aliasy na liście, szuka po nich i podgląda
  na żywo „wpisane → kanon · w nagłówku: …”; oznaczenie katalogowe trafia dokładnie (`C4` nie znajduje
  już NGC4258), a w trakcie pisania - początkiem nazwy (`sh2 13` nie gubi Sh2-131), tak samo
  w listwie filtrów i na liście obiektów do wydania. Nowy wiersz Porządków „Nagłówek inny niż
  zatwierdzony folder” pokazuje klatki nazwane z folderu, których plik mówi co innego, a słownik zna
  dwie nowe pary: M44 to NGC2632, Sh2-229 to IC405.

- **Rodowód stosów liczy się przy każdym przyjęciu i trafia celniej.** Przeliczenie rodowodu stosów
  jest teraz ostatnim etapem każdego „Przyjmij nowe” i gestów, które go ruszają - nie trzeba osobno
  klikać „Policz rodowód stosów”, a przerwanie Dostawy zatrzymuje je od razu. Historię obróbki stosu
  (listę klatek zapisaną przez PixInsight) skan zapamiętuje w bazie, więc kolejne przeliczenia nie
  czytają nagłówków stosów z dysku. Klatki z tej historii program dopasowuje najpierw po nazwie - także
  gdy plik przemianowałeś później w Horreum - a dopiero potem po temperaturze i liczbie; gdy plik nie
  zapisał, których klatek użył, panel mówi „plik użył N z M klatek okna” i prosi o potwierdzenie na
  liście.

- **Zapis nagłówka pilnuje reguł karty FITS, zanim cokolwiek zapisze.** Wartość spoza drukowalnego
  ASCII, dłuższa niż mieści karta albo nowa karta o niedozwolonej nazwie odpada już w podglądzie panelu
  „Popraw nagłówki…” i edycji komórki, a nie dopiero przy zapisie. FITS nie zapisze już wartości
  dłuższej niż 68 znaków (dotąd dzielił ją po cichu na karty kontynuacji). Zapis, który uciąłby
  zastany komentarz karty, odmawia, a panel ma pole „komentarz (opc.)”, którym podasz krótszy. Nowy
  nagłówek XISF przechodzi parser, zanim trafi do pliku.

- **Planer stawia wyżej cele, które dobrze wypełniają kadr.** Po widoczności i brakach w materiale
  kolejność bierze teraz kadr: najpierw cele wypełniające co najmniej 30 % kadru, potem mozaiki,
  potem za małe, na końcu bez kadrowania - i dopiero w tych grupach rządzi koszt Księżyca. Przy
  wybranej soczewce zestawu („Patrzę oczami zestawu:”) kolejność bierze kadr tego zestawu, a zestaw
  „najlepszego dopasowania” wybierany jest po wypełnieniu kadru.

- **Hamulec „Sprawdź obecność” da się świadomie zwolnić.** Gdy kandydatów do oznaczenia jako
  zniknięte jest więcej niż próg hamulca, okno „Zapis ponad progiem hamulca” podaje liczbę kopii,
  których zniknięcie sprawdzenie potwierdziło (domyślnie „Anuluj”). Zatwierdzenie oznaczy wyłącznie te
  kopie, a jeśli przy zapisie dysk pokaże inny zbiór, nic nie zostanie zapisane.

- **Obiektyw lustrzanki na kilku ogniskowych to kilka pozycji osi teleskopu.** Gdy zdjęcia RAW spod
  jednej nazwy obiektywu mają w EXIF różne ogniskowe, oś teleskopu rozdziela je po ogniskowej, bo od
  niej zależą kadr i skala; nazwa zostaje przy ogniskowej, którą teleskop już deklarował. Scalenie
  ręką („Scal”) wstrzymuje ten podział.

- **Baza z nowszej wersji Horreum nie otworzy się w starszej.** Gdy baza ma schemat, którego program
  jeszcze nie zna, Horreum mówi to oknem komunikatu („Zaktualizuj Horreum. Baza zostaje nietknięta.”)
  i zostaje przy dotychczasowej bazie albo startuje bez bazy - zamiast otworzyć ją po cichu i pisać
  obok faktów, których nie widzi. Wiersz poleceń odmawia tym samym zdaniem. Ochrona działa od tej
  wersji w przód: 0.10.0 i starsze jej nie mają.

### Naprawione

- **Okno nie zamiera przy pracy na dużym archiwum.** Zbiór klatek po kliknięciu filtra składa się
  w tle - tabela nie staje już na sekundę przy każdym kliknięciu w listwie, a w czasie wczytywania
  akcje widoku czekają z wyjaśnieniem. W tle liczą się też pokrycie kolumn w panelu „Pola” (dotąd
  przeliczane po każdej Dostawie, nawet bez zmian w kartach) i sonda katalogu w „Wskaż katalog…”,
  a widoki przeładowują się raz na koniec przebiegu Dostawy zamiast po każdym etapie. „Przyjmij
  nowe”, „Skanuj”, „Sprawdź obecność” i „Wciągnij stosy…” sprawdzają źródło poza oknem, więc
  odłączony dysk sieciowy nie wiesza programu - mówi „Źródło niedostępne: … - wskaż katalog.”

- **Master flat z kartą `IMAGETYP = FLAT` nie liczy się już jako surowy flat.** Program brał taki
  plik za zwykłą klatkę flat, choć to gotowy master. Teraz plik XISF z historią integracji jest
  masterem flat przy skanie i przy „Wciągnij z WBPP…”. Już przyjęte pliki przelicza
  `horreum rederive-kind`, a kartę w samym pliku poprawia `horreum header-fix`.

- **Cofnięcie mówi, co się nie udało, i przywraca cały stan.** Cofnięcie zmiany nazw plików i zapisu
  makra pokazuje porażki z pierwszym powodem, a „Cofnij” zostaje, dopóki jest co cofać; zapis, który
  niczego w plikach nie zmienił, nie zapala „Cofnij” na pusto. Cofnięcie zapisu nagłówka składa plik
  bajt w bajt, gdy to możliwe, a inaczej okno mówi „cofniętych semantycznie”; cofnięcie karty
  `OBJECT`, która zdjęła Twoje wcześniejsze „Cofnij przypisanie”, przywraca też to cofnięcie. Zmiana
  nazw przerwana w połowie (awaria, odłączony dysk) domyka się przy następnym skanie, a zapis
  oznaczony jako nieudany, który jednak trafił do pliku, potwierdza najbliższy skan.

- **Zapis nagłówka nie nadpisze zmiany, którą w tym czasie zrobił inny program.** Plik podmieniany
  jest razem z kopią wersji wypieranej i sprawdzany wobec odcisku sprzed zapisu: gdy inny program
  zmienił go w trakcie, jego wersja wraca na miejsce, a zapis kończy się jako zablokowany z podaniem
  ścieżek. Dopisanie karty do pliku XISF, którego karty mają postać z zamykającym znacznikiem, nie
  zagnieżdża już nowej karty w starej; strukturę kart, której program nie rozumie, odrzuca bez zapisu.

- **Klatka nie zostaje na stałe bez nagłówka.** Wpis klatki ze skanu trafia do bazy w całości albo
  wcale - awaria w połowie nie zostawia klatki bez zeznania ani licznika raportu bez pokrycia. Gdy pod
  znaną ścieżką leży nowa treść, nowa klatka i przepięcie kopii zapisują się razem, a odmowa cofa oba,
  więc kolejny skan nagrywa nagłówek od nowa. Kopia nieczytelna dostaje rodzaj awarii (dysk czy plik)
  już przy pierwszym nieudanym odczycie, z kodem błędu Windows w diagnozie.

- **Planer liczy kadr osobno dla każdej kamery na tym samym teleskopie.** Teleskop z dwiema kamerami
  o różnym polu widzenia nadpisywał sobie kadrowanie, więc część celów dostawała złą liczbę paneli
  mozaiki. Teraz kadr należy do zestawu (teleskop i kamera), a zestawy jednej optyki mają w planerze
  różne nazwy.

- **Podpowiedź obiektu gotowego stosu pokazuje obiekt, nie filtr.** Dla stosu bez nazwy kolumna
  „Obiekt” podpowiadała nazwę folderu rodzica, czyli w drzewie `STACKS` nazwę filtra (`⟨Ha⟩`,
  `⟨NoFilter⟩`). Teraz podpowiada folder obiektu.

- **Propozycja rodowodu wskazuje materiał także przy karcie teleskopu do naprawy.** Stos, którego
  karta teleskopu jest przestarzała (albo niesie nazwę montażu), dostawał w propozycji pustkę -
  teraz widzi noc zapisaną jednym innym teleskopem, z ostrzeżeniem o rozjeździe, tak jak gotowy
  rodowód.

- **„Brakujące kopie” pokazują także klatkę wycofaną**, której jedna z kopii zniknęła - to fakt
  o pliku, prawdziwy niezależnie od wycofania. **„Duplikaty” nie pokazują klatki wycofanej ani
  zastąpionej** - lista i gest scalania mówią teraz to samo.

- **Perspektywa zapisana nowszą wersją nie udaje, że działa.** Otwarta w wersji, która nie zna
  któregoś jej warunku, pokazywała szerszy zbiór pod tą samą nazwą. Teraz pasek kryteriów mówi
  „zapisana w nowszej wersji - N warunków pominiętych” i nazywa je, a ponowny zapis tej samej
  perspektywy ich nie kasuje.

- **Plakietka „Porządki (N)” zmienia się od razu po geście.** Po „Przywróć” albo „Wycofaj”
  w Zbiorach klasycznych, po gestach panelu rodowodu, po zapisie do plików i po cofnięciu makra
  albo zmiany nazw liczba przy Porządkach zostawała stara, dopóki nie wszedłeś w Porządki.

- **Komunikaty stoją na swoim ekranie.** Planer bez stanowiska nie zgłasza tego na pasku Dostawy,
  tylko pokazuje u siebie pusty stan z przyciskiem „Ustaw stanowisko…”, a po wskazaniu stanowiska plan
  liczy się sam; inne błędy planera widać tak jak dotąd. Zdanie osi stanowisk po przebiegu Dostawy nie
  przykrywa statusu etapu - czeka na wejście w Porządki.

- **Mapa stanowisk nie rysuje kresek przez cały ekran.** Stanowisko na drugim końcu świata
  (np. Nowa Zelandia) psuło kontury lądów; punkt na skraju mapy nie leży już na krawędzi,
  a po wskazaniu stanowiska jest ono zaznaczone na liście i na mapie.

- **Podgląd nowych nazw stoi w kadrze.** Kolumna „nazwa →” stoi zaraz po kolumnach bazowych,
  zamiast na końcu tabeli poza ekranem.

- **„Przenieś” w planerze nie obiecuje gestu, który zaraz odmówi.** Gdy cel sieroty ma już własne
  oznaczenie, przycisk jest wygaszony, a podpowiedź mówi dlaczego.

- **Angielski interfejs mówi po angielsku także w opisie filtra i powodach obecności.** Opis drzewa
  filtra na pasku kryteriów i powody zatrzymania „Sprawdź obecność” brały dotąd polski tekst
  programu; teraz idą z katalogu języka.

- **Okno mieści się na niższym ekranie.** Listwa filtrów w Zbiorach klasycznych przewija się zamiast
  wymuszać wysokość okna, więc Horreum da się zmniejszyć w pionie znacznie bardziej niż dotąd.

- **Zepsuta baza nie wywraca programu.** Plik, który nie jest bazą Horreum, obcięta kopia albo
  katalog wskazany zamiast pliku dają okno „Nie udało się otworzyć bazy” z powodem - zarówno
  w „Otwórz bazę…”, jak i przy starcie z zapamiętaną bazą. Okno zostaje przy dotychczasowej bazie
  albo startuje bez bazy, a pliku nie trzyma otwartego, więc od razu da się go przenieść albo
  usunąć. Wersja w jednym pliku dotąd po prostu nic nie pokazywała.

- **Plik chwilowo zajęty nie blokuje przeniesienia.** Gdy przy „Zmień obiekt…”, „Uzgodnij pliki…”
  albo zmianie nazw plik trzyma przez moment inny program (Eksplorator, indeksowanie, antywirus),
  Horreum czeka chwilę i próbuje ponownie, zamiast od razu zgłosić pozycję jako zablokowaną. Gdy
  plik dalej jest zajęty, powód mówi „plik zajęty przez inny program - spróbuj ponownie za chwilę”
  zamiast surowego komunikatu systemu.

### Wiersz poleceń

- **`horreum header-fix`** poprawia w plikach, w miejscu, kartę `IMAGETYP` mastera według historii
  integracji i kartę `FILTER` według folderu filtra. Bez `--apply` tylko liczy i zapisuje plan;
  `--apply --plan` wykonuje wyłącznie ten plan, a `--undo` cofa zapis po numerze z raportu.
- **`horreum rederive-kind`** przelicza rodzaj już przyjętych plików XISF (master flat zapisany jako
  FLAT); czyta nagłówki, pisze tylko bazę. Bez `--apply` tylko podgląd i plan.
- **`horreum stack-versions`** kopiuje skadrowane warianty `_autocrop` ze starego drzewa obróbki do
  biblioteki `STACKS` archiwum; bez `--apply` tylko pokazuje plan.
- **`horreum object-change finish|undo`** dokańcza albo cofa przebieg „Zmień obiekt…” po numerze ze
  zdania wyniku - także po zamknięciu okna albo awarii.
- **`horreum streaks`** szuka śladów (meteor, satelita, samolot) w klatkach jednego katalogu, bez
  bazy. Raport (CSV, wycinki PNG, manifest) pisze wyłącznie do nowego albo pustego katalogu `--out`,
  poza katalogiem klatek i korzeniem archiwum, które tylko czyta; rodzaj śladu to propozycja.
- **`horreum project --object`** wydaje obiekt do WBPP z wiersza poleceń (bez `--apply` tylko podgląd).
- **`horreum observatory assign|clear`** wskazuje stanowisko klatkom bez GPS i cofa to wskazanie (bez
  `--apply` tylko podgląd).
- **`horreum camera`** listuje kamery i przyjmuje piksel matrycy wpisany ręką (`--pixel`) albo go
  cofa (`--clear-pixel`).
- **`horreum scan --reread-raw`** czyta ponownie wszystkie pliki RAW, żeby dociągnąć nowe fakty
  z EXIF (wymiary kadru, piksel).
- **`horreum plan --min-fill --max-panels`** - filtr kadru planera, a wypełnienie kadru trafia też do
  wydruku i `--json`.

## [0.10.0] - 2026-09-26

Wydanie o **ekranie zaraz po geście** - o chwili, w której kliknąłeś i patrzysz, co się stało.
Gest potrafił zdjąć z widoku wszystkie klatki i zostawić pusty ekran z ogólnikiem, zaznaczenie
w listwie filtrów uciekało poza kadr, nazwa perspektywy zostawała przy zbiorze, którego już nie
oglądałeś, a trzy sąsiednie gesty osi obiektu liczyły każdy po swojemu. Teraz pusty ekran mówi, co
zasłania klatki, i jednym przyciskiem je odsłania; wybór zostaje tam, gdzie go widziałeś; nazwa
idzie za zbiorem; gesty mówią jedną gramatyką liczb. Doszła jedna nowa rzecz: kopia nieczytelna
mówi, czy zawiódł dysk, czy plik. Schemat bazy rośnie do wersji 19 - migracja wjeżdża sama przy
pierwszym otwarciu, bez ruszania istniejących wierszy.

### Dodane

- **Kopia nieczytelna mówi, KTÓRA to sytuacja: dysk czy plik.** Wiersz „kopie nieczytelne" mówił
  jedną liczbą i tym samym zdaniem oskarżał plik - także wtedy, gdy zawiódł dostęp do dysku, a plik
  był zdrowy. Teraz baza zapamiętuje przy każdej oznaczonej kopii rodzaj awarii i diagnozę ostatniej
  próby odczytu: „dysk/dostęp: …" (system nie oddał bajtów - sprawdź wolumin i uprawnienia),
  „nagłówek nie przechodzi parsera: …" (plik do zgłoszenia albo naprawy) albo „baza danych: …"
  (błąd po stronie programu - powtórz skan). Podpowiedź wiersza w kolejce przeglądu podaje rozbicie
  po rodzaju, kolumna „Powód" w panelu kopii stawia rodzaj przed diagnozą, a podpowiedź naprawy
  kieruje do tej kolumny zamiast kazać „odzyskać plik". Kopia przemianowana po oznaczeniu nie gubi
  już powodu (dotąd szukany był w dzienniku po starej ścieżce). Schemat bazy rośnie do wersji 19;
  migracja przy pierwszym otwarciu, bez ruszania istniejących wierszy.

### Naprawione

- **Pusty ekran mówi, co zasłania klatki - i jednym kliknięciem je odsłania.** Gdy gest zdjął
  z widoku wszystkie klatki (na przykład cofnąłeś nazwę przy widoku zawężonym do jednego obiektu),
  pasek stanu podawał „odsłoni je „× Wyczyść zbiór”", a kiedy zdanie zgasło, środek ekranu mówił
  ogólne „zmień filtr lub perspektywę" - przy zawężeniu listwą filtrów to nie był ruch, który
  cokolwiek odsłania. Teraz pusty ekran mówi, czym widok jest zawężony, i ma pod zdaniem przycisk,
  który wykonuje właściwy gest: gdy perspektywa ma klatki, a zasłaniają je filtry, przycisk zdejmuje
  tylko filtry i zostawia Cię w tej perspektywie (na przykład w „Do przeglądu" przy pozostałych
  klatkach); gdy perspektywa nie ma ani jednej klatki, przełącza na „Przegląd". Klatki gestu, które
  wrócą do widoku, są zaznaczone.

- **Zaznaczona wartość w listwie filtrów nie ucieka z oczu.** Po cofnięciu nazwy obiektu, który
  był wybrany w listwie, znacznik `✓` przeskakiwał na górę listy, a lista zostawała przewinięta
  w dół - zaznaczenie znikało z widoku, choć dalej zawężało zbiór. Teraz lista idzie za wyborem,
  który widziałeś albo właśnie kliknąłeś. Wybór widoczny choćby częściowo zostaje dokładnie tam,
  gdzie był, więc drugie kliknięcie w cyklu `✓` / `⊖` trafia w ten sam wiersz.

- **Krótkie grupy listwy filtrów pokazują całe wiersze.** Filtr, Rodzaj i Teleskop ucinały piąty
  wiersz w połowie. Wysokość grupy liczy się teraz z realnej wysokości wiersza, więc mieści cztery
  pełne wiersze także przy innym skalowaniu ekranu.

- **Nazwa perspektywy opisuje zbiór, który naprawdę oglądasz.** Lista perspektyw zostawała przy
  starej nazwie w kilku sytuacjach: po „× Wyczyść zbiór" albo „Wyczyść" w panelu filtra
  w „Kalibracji" (nazwa „Kalibracja" nad pełnym zbiorem), po „Pokaż klatki celu" z planera, gdy
  widok był w „Duplikatach", po kliknięciu w listwie wartości, która definiowała zapisaną
  perspektywę, i po każdym etapie Dostawy (wtedy wracała do „Przeglądu" nad zawężonym zbiorem).
  Teraz nazwa idzie za zbiorem: przechodzi na perspektywę, która go opisuje, albo zostaje, gdy
  zbiór nadal jest jej zbiorem (na przykład „Duplikaty" po wyczyszczeniu filtrów). Grupowanie
  zostaje takie, jakie ustawiłeś, a „Wydaj na stół…" zapisuje w manifeście właściwą nazwę.

- **Wskazówka po geście ma własne miejsce na pasku stanu i nie ucina się.** Raport gestu
  i wskazówka „co teraz zrobić" konkurowały o jedno pole paska - przy długim raporcie wskazówka
  znikała za krawędzią. Teraz stoi obok raportu, a pełne zdanie zawsze jest w podpowiedzi paska.

- **Kolejka przeglądu obiektów nie rezerwuje pustego miejsca.** Lista kolejki zwija się do swojej
  treści, a „Biblioteka" obiektów pokazuje prawie dwa razy więcej wierszy (19 zamiast 10).

- **„Przywróć cofnięte przypisanie" liczy tak samo, jak dwa sąsiednie gesty.** Przy 120
  zaznaczonych klatkach, z których 30 było cofniętych, zdanie mówiło „Przywrócono przypisanie na
  30 z 30 klatek" - reszta zaznaczenia nie liczyła się nigdzie, a nagrobki bez zapamiętanego obiektu
  dostawały osobne zdanie. Teraz trzy gesty osi obiektu mówią jedną gramatyką: „Przywrócono
  przypisanie na 30 z 120 klatek · kalibracja: N · nie było czego przywrócić: N · bez zapamiętanego
  obiektu: N", a gdy nie ma czego przywrócić - „0 z N" z tym samym rozbiciem, bez osobnego
  komunikatu. To samo rozbicie dostały „Zatwierdź ze ścieżki…" (dotąd sumowało liczby bez powodów)
  i „Przypisz obiekt…" z kolejki (dotąd płaskie „pominięto N"). Klatki, których klinga nie zapisała
  przez własny błąd (na przykład konflikt nazwy), mają własny człon zamiast udawać „zmieniły się
  w międzyczasie".

- **Remis w kolejce przeglądu rozstrzyga porządek naturalny nazwy.** Pozycje o równej liczbie
  klatek stały w porządku znaków: „Caldwell 12" przed „Caldwell 3", „NGC 700" przed „NGC 7000".
  Teraz liczba w nazwie liczy się jak liczba; suma klatek dalej prowadzi, a obie połówki tej samej
  nazwy (nietknięta i cofnięta ręką) stoją obok siebie.

- **„Zniknięte" nie pokazuje klatki, której gest wycofania nie zamknie.** Klatka zastąpiona
  następczynią, której jedyna kopia zniknęła z dysku, trafiała do listy roboty „Zniknięte", a
  „Wycofaj" ją odrzucał. Teraz zostaje wyłącznie w „Zastąpione"; licznik w Porządkach i podsumowanie
  passa obecności liczą to samo.

- **Klatka bez rozpoznanego formatu nie wypada z kolejki po cichu.** Light bez zapisanego formatu
  pliku nie trafiał ani do „bez nazwy w nagłówku", ani do „format bez karty (RAW)", choć widok
  „Do przeglądu" go pokazywał - suma kubełków kolejki nie zgadzała się z widokiem. Teraz format
  nieznany liczy się jak każdy light z kartą (droga naprawy: karta w nagłówku albo ręka).

- **Kolumna „Powód" w panelu kopii mieści się bez przewijania.** Realna diagnoza błędu dostępu
  powtarzała pełną ścieżkę pliku i rozpychała kolumnę na dwie szerokości panelu, zgniatając
  „Ścieżkę" do kilkunastu znaków. Diagnoza nie powtarza już ścieżki (niesie ją własna kolumna
  i podpowiedź), a resztę miejsca dostaje „Powód".

## [0.9.1] - 2026-08-16

### Naprawione

- **Cofnięcie przypisania przestało gubić klatki bez słowa.** Gdy zawęziłeś widok do jednego
  obiektu i zdjąłeś mu nazwę, klatki znikały z ekranu w tej samej chwili - bo lista szuka po
  nazwie, którą właśnie zdjęła Twoja ręka. Zostawał pusty widok i pytanie, czy gest w ogóle się
  udał. Teraz zdanie po geście mówi, ile klatek wyszło poza widok, i podaje JEDNO kliknięcie,
  które je odsłoni. Recepta zależy od tego, czym widok jest zawężony: gdy trzyma go perspektywa,
  zdanie wskazuje perspektywę „Przegląd" - przycisk „Wyczyść zbiór" by tu nie pomógł, bo flag
  perspektywy nie tyka. Ten sam człon dostały gesty żywotności klatki, gdzie zniknięcie celu
  z widoku jest wręcz regułą: wycofana klatka wypada z „Zniknięte" natychmiast po geście.

- **Po cofnięciu przypisania widać, że da się je przywrócić - i kiedy.** Droga powrotu istniała
  od dawna, ale dowiadywałeś się o niej dopiero po najechaniu myszą na kontrolkę, czyli nie wtedy,
  kiedy jest potrzebna. Teraz podaje ją zdanie po geście. Gdy klatki wyszły z widoku, zdanie mówi
  „potem przywrócisz…", bo dopóki nie wrócą na ekran, nie ma czego zaznaczyć - a kontrolka jest
  w tej chwili wyszarzona. Kolejność w zdaniu jest kolejnością, w której da się te gesty wykonać.

- **Cofnięcie i przywrócenie mówią o tych samych obiektach w tej samej kolejności.** Oba zdania
  wypisują trzy nazwy i liczbę reszty, ale robiły to w dwóch różnych porządkach - jedno w kolejności
  klatek, drugie alfabetycznie. Przy siedmiu obiektach dawało to dwie rozłączne trójki, więc nie
  dało się wzrokiem sprawdzić, czy przywrócenie objęło to samo, co cofnięcie.

## [0.9.0] - 2026-08-15

Wydanie o **czytelności ekranu** - o tym, żeby to, co widzisz, zgadzało się z tym, co program
naprawdę wie. Każda pozycja niżej ma ten sam kształt: fakt siedział w bazie, a ekran mówił coś
innego albo milczał. Lista klatek pokazywała adres kopii, której na dysku dawno nie ma (**128
gotowych obrazów** Twojego archiwum), liczby przy filtrach liczyły na całym katalogu zamiast na
zawężonym widoku, znacznik „wycofana" ucinał się poza krawędź kolumny, a szarość stanów w jasnym
motywie miała kontrast poniżej progu czytelności. Doszła też jedna nowa powierzchnia: obrazy,
którym zniknęła jedna z dwóch kopii, mają wreszcie własne miejsce zamiast wpisu widocznego tylko
po najechaniu myszą.

Osobny wątek tego wydania: **kolumna „Obiekt" zaczęła mówić pełnym zdaniem.** Do tej pory kilka
różnych stanów wyglądało w niej znak w znak tak samo, a nazwa zdjęta Twoją ręką znikała bez śladu
tego, co zdjęła. Teraz każdy stan ma własny znacznik i własną receptę - opisuje je nowa tabela
w [instrukcji](doc/instrukcja.md).

### Dodane

- **Obrazy, którym zniknęła jedna z kopii, mają wreszcie swoje miejsce - „Brakujące kopie".** Gdy
  ten sam obraz leżał w dwóch miejscach i jedno z nich przepadło, program wiedział o tym, ale nie
  miał jak Ci tego pokazać inaczej niż po najechaniu myszą na pojedynczy wiersz. Przy 128 takich
  obrazach to znaczyło: fakt jest w bazie, a zobaczyć go nie sposób. Teraz Porządki mają osobną
  pozycję, a Zbiory - własną perspektywę, więc widzisz je wszystkie naraz i możesz filtrować jak
  każdy inny zbiór. **Ta pozycja celowo NIE liczy się do odznaki „tu jest robota"** i nie jest
  pogrubiona: klatka żyje, plik jest na dysku, nic nie zginęło - to zapis historii, nie zadanie.
  Odróżnia się przy tym od dwóch sąsiadów, z którymi łatwo ją pomylić: „Zniknięte z dysku" to
  klatki BEZ ani jednej żywej kopii (tam robota jest), a „Duplikaty" to nadmiar kopii, nie ubytek.

### Naprawione

- **Liczby przy filtrach po lewej przestały kłamać w zawężonych widokach.** Gdy patrzyłeś na
  wybraną perspektywę - „Duplikaty", „Zniknięte", „Brakujące kopie" i cztery pozostałe - i klikałeś
  wartość w liście filtrów, liczby przy pozostałych wartościach oraz godziny przy obiektach liczyły
  się na CAŁYM katalogu, a nie na tym, co masz przed sobą. Wychodziło z tego zdanie sprzeczne samo
  ze sobą: „NGC7000 · 60 h" obok listy na trzy pozycje. Teraz obie strony ekranu liczą to samo.
  Dotyczyło pięciu z siedmiu perspektyw; dwie najstarsze („Duplikaty", „Do przeglądu") liczyły
  dobrze od początku.
- **Lista klatek pokazuje adres kopii, KTÓRA ISTNIEJE.** Gdy jeden obraz leży na dysku w dwóch
  miejscach i jedno z nich zniknie - a tak stało się przy uporządkowaniu drzewa gotowych stosów -
  program pokazywał ten adres, który wjechał do bazy PIERWSZY, nawet jeśli plik spod niego dawno
  przepadł. Robił to po cichu: znacznik „zniknięta" zapala się dopiero, gdy nie ma ANI JEDNEJ
  żywej kopii, więc taki wiersz wyglądał zupełnie zwyczajnie. Na Twoim archiwum dotyczyło to
  **128 gotowych obrazów** - najcenniejszej części zbioru. Teraz spośród kopii wygrywa ta obecna,
  a gdy żadnej nie ma, wiersz dalej pokazuje swój ostatni znany adres i dalej jest oznaczony jako
  zniknięty - bo wtedy właśnie ta ścieżka jest wskazówką, gdzie szukać kopii zapasowej. Ta sama
  poprawka objęła panel „Klatki obiektu" i listę klatek do przypisania nazwy.
- **Klatka zastąpiona przestała liczyć się jako robota do zrobienia.** Gdy edycja RAW-a tworzy nową
  tożsamość, stara klatka zostaje w bazie jako historia - ale wewnętrzna kontrola spójności liczyła
  ją dalej do populacji „do przerobienia", więc bilans nie domykał się o jedną klatkę i kontrola
  świeciła na czerwono niezależnie od tego, czy coś naprawdę jest nie tak. Teraz zastąpiona ma
  własną, jawną pozycję w rozkładzie - tak samo jak wycofana ręką.
- **Stary adres przestał być śmieciem i stał się historią przeprowadzki.** Najechanie na ścieżkę
  takiego obrazu pokazuje teraz dodatkowo, gdzie leżał wcześniej - odpowiedź na pytanie „przecież
  to było w innym folderze, gdzie się podziało" jest na ekranie, a nie tylko w bazie.
- **Znacznik „wycofana" znowu widać.** Klatka, którą wycofałeś ręką, miała mówić o tym tekstem,
  a nie samym kolorem tła - żeby wiersz tłumaczył się sam także w drugim motywie i komuś, kto nie
  rozróżnia odcieni. W układzie domyślnym nie mówił ANI RAZU: dopisek stał na końcu ścieżki, a
  ścieżka pliku z archiwum jest kilka razy szersza niż kolumna, więc dopisek zawsze wpadał
  w wielokropek. Teraz stoi z przodu, tak samo jak licznik kopii przy duplikatach.
- **Kolumna „Obiekt" mówi, CO zdjęła Twoja ręka.** Po cofnięciu przypisania komórka pokazywała
  sam znaczek `↺` bez nazwy, jeśli nazwa nie stała w nagłówku pliku - a przy plikach RAW nie stoi
  tam prawie nigdy. Wychodziła z tego kolumna kilkudziesięciu identycznych znaczków, po której nie
  dało się poznać, którą klatkę zdjęto z czego. Program pamięta zdjęty obiekt w bazie od poprzedniego
  wydania, ale ekran o tę pamięć nie pytał - teraz pyta i pokazuje `↺ NGC2903`. Klatki wjechane
  jeszcze przed tą pamięcią zachowują się jak dotąd i mają własne wyjaśnienie w podpowiedzi, bo
  wspólne kłamałoby o werdykcie ręki tam, gdzie go nie ma.
- **Szare stany daje się przeczytać w jasnym motywie.** Kolor, którym program wygasza stany bez
  roboty (kalibracja, brak wartości, cofnięte przypisanie), miał w motywie jasnym kontrast **2,64:1**
  przy progu czytelności 4,5:1 - czyli poniżej nawet łagodniejszego progu dla dużego tekstu. Nowe
  odcienie sprawdzono na KAŻDYM tle, na które ten kolor pada: zwykły wiersz, wiersz naprzemienny,
  siedem teł stanów i belka grupowania.
- **Nagłówek grupy przestał udawać, że kalibracja ma przypisany obiekt.** Przy „Grupuj wg: Obiekt"
  belka `▸ DARK (14)` była malowana białym pogrubieniem dokładnie tak samo jak `▸ CTB1`, choć
  komórki pod nią były szarą kursywą - stan znała komórka, a belka nie. Teraz belka niesie ten sam
  stan i tę samą podpowiedź co wiersz pod nią, a gdy grupa jest niejednorodna, milczy zamiast
  zgadywać stan większości.
- **Nazwa, której program nie rozpoznał, ma własny znacznik.** Klatka z nazwą nie do rozpoznania
  („popraw ją w pliku albo wskaż obiekt ręką") wyglądała znak w znak tak samo jak klatka
  kalibracyjna („tu nie ma czego poprawiać") - różniła je wyłącznie sąsiednia kolumna „Rodzaj".
  Teraz nierozpoznana nazwa dostaje `?`, więc każdy znacznik w tej kolumnie znaczy dokładnie jedną
  rzecz: `↺` zdjęte ręką, `⟨…⟩` podpowiedź z nazwy folderu, `?` nazwa nierozpoznana, brak znacznika
  - nie ma tu roboty.
- **Lista „Grupuj wg" pokazywała wewnętrzne klucze zamiast nazw kolumn.** Sześć z siedmiu pozycji
  wyświetlało się jako `grid.col.kind` czy `object.col.name` - nagłówki tych samych kolumn w tabeli
  były przy tym poprawne, więc rozjazd łatwo było przeoczyć. Program pilnuje teraz sam, że żaden
  napis widoczny w oknie Zbiorów nie jest kluczem wewnętrznym.
- **Podpowiedź nad grupą przestała orzekać o całej grupie na podstawie jednego wiersza.** Zdanie
  wyjaśniające stan grupy brało treść z pierwszej klatki w kubełku, a pierwsza zależy od tego, jak
  akurat posortowałeś tabelę - więc po kliknięciu w nagłówek kolumny zdanie potrafiło się zmienić,
  choć grupa była ta sama. Teraz mówi tylko to, co jest prawdą o wszystkich wierszach grupy, a gdy
  wiersze się różnią - milczy.

## [0.8.0] — 2026-08-11

Wydanie o **odwracalności** — o tym, żeby żaden gest w Horreum nie był ślepym zaułkiem. Do tej pory
trzy miejsca w programie potrafiły zamknąć Cię bez drogi powrotu: masowe „Cofnij przypisanie" nie
dawało się cofnąć drugi raz, kuratela celu osierocona po przebudowie katalogu była w planerze
niewidoczna i nieusuwalna, a klatka, której wszystkie kopie zniknęły z dysku, tkwiła w kolejkach
roboczych na zawsze — jedynym wyjściem było skasowanie wiersza razem z jego historią. Wszystkie
trzy dostały teraz gest powrotny. Osobno: kolumna „Obiekt" przestała kłamać o tym, co się właśnie
stało, klatka zastąpiona po edycji RAW-a stała się widoczną historią zamiast zaległej roboty,
a skan przestał cicho połykać katalogi, do których stracił dostęp w trakcie pracy.

### Dodane

- **Cofnięcie ma drogę powrotu.** Menu „Obiekt ▾" dostało trzecią pozycję — **„Przywróć cofnięte
  przypisanie"** — dla klatek, którym zdjąłeś nazwę przez pomyłkę. Program pamięta, CO zdjął (nowa
  kolumna w bazie, migracja **0017**), więc przywrócenie nie jest zgadywaniem z dziennika: dostajesz
  z powrotem dokładnie ten obiekt, który klatka miała. Pozycja jest widoczna zawsze — wygaszona, gdy
  nie ma czego przywracać — żebyś wiedział, że odwracalność istnieje, zanim jej będziesz potrzebować,
  nie dopiero po pomyłce. Zaznaczenie przeżywa też samo odświeżenie listy, więc gest naprawczy ma na
  czym pracować.
- **Sierota kurateli dostaje miejsce w planerze i dwie drogi powrotu.** Gdy przebudowa katalogu celów
  usunie albo przemianuje nazwę, którą oznaczyłeś („zaplanowany", „zrobiony"...), Twoja decyzja
  wcześniej znikała z ekranu — została w bazie, ale nie było jej ani widać, ani jak zdjąć inaczej niż
  z konsoli. Planer pokazuje teraz osobną sekcję z takimi celami i rozróżnia **dwa stany osierocenia**:
  nazwa zniknęła całkiem (**zdejmujesz** oznaczenie) albo katalog tylko ją przeniósł pod nowym kanonem
  (**przenosisz** kuratelę na właściwe miejsce, zamiast zostać z martwym wpisem) — a trzeci gest,
  **„Cofnij zdjęcie"**, odwraca pomyłkowe zdjęcie oznaczenia. „Przenieś" pyta przy tym, czy cel
  docelowy nie ma już WŁASNEJ, świeższej decyzji — jeśli ma, program odmawia zamiast po cichu
  nadpisać ją starszym wierszem.
- **Klatka, której ostatnia kopia zniknęła z dysku, ma teraz gest wycofania.** Do tej pory taka
  klatka tkwiła w kolejkach roboczych bez końca, a jedynym wyjściem było skasowanie wiersza razem
  z nagłówkiem, kartami i rodowodem. Nowy gest **„Wycofaj"** (migracja **0018**) zdejmuje ją
  z kolejek — ale zostaje w archiwum, w godzinach naświetlenia i w rodowodzie stosów: została
  naświetlona naprawdę, więc jej historii program nie kasuje. Jeśli plik wróci (dysk odłączony,
  ścieżka naprawiona), Porządki dostają osobny, klikalny wiersz, który to zauważa — powrót pliku
  **nie** gasi wycofania automatycznie, bo to byłoby cofnięciem Twojej decyzji przez zwykły re-skan.
  Komórka w siatce mówi to wprost, własnym kolorem i dopiskiem, nie tylko tłem.
- **Foldery „STACKS" wchodzą do zwykłego skanu.** Jeśli w katalogu `STACKS` bezpośrednio w korzeniu
  archiwum trzymasz gotowe obrazy, zwykły skan (nie tylko osobna droga „Stosy") wciąga je teraz
  normalnie — z tym samym sitem wersji pochodnych (kadrowane, po ABE, bez gwiazd), które chroni
  resztę archiwum. Folder o tej samej nazwie gdzie indziej w drzewie — Twój własny roboczy podfolder
  przy obiekcie — sito świadomie omija.
- **Trzy nowe gramatyki katalogowe.** Pozostałości supernowych z katalogu Greena, obiekty ESO
  i zwarte grupy galaktyk Hicksona (HCG) są odtąd rozpoznawane po nazwie — 297 kanonów sprawdzonych
  wobec katalogu celów, zero kolizji z tym, co już było.
- **Szybsza droga do częstych gestów w Zbiorach.** `Enter` w szukajce bierze pierwsze widoczne
  trafienie, `Ctrl+F` stawia w niej kursor, dwuklik na pozycji kolejki przeglądu odpala jej akcję
  wprost. Menu „Obiekt ▾" pamięta **ostatnio użyte kanony** z dziennika, więc powtórne przypisanie
  tego samego obiektu to dwa kliknięcia zamiast pięciu.

### Zmienione

- **Klatka zastąpiona (po edycji pliku RAW) przestaje być traktowana jak zaległa robota.** Kolejka
  przeglądu, panel rodowodu stosu i godziny obiektu liczyły ją tak, jakby czekała na Ciebie — a to
  ta sama fotografia po edycji w Lightroomie czy Camera Raw, nie nowa klatka do rozpoznania. Dostaje
  teraz własną perspektywę **„Zastąpione"**, wiersz informacyjny w Porządkach (widoczny, ale bez
  odznaki „tu jest robota") i mówi o sobie wprost w siatce: „zastąpiona przez #N", własne tło,
  tooltip z adresem następczyni.
- **Program nie cofa ręcznych decyzji, gdy dojeżdża nowy materiał — domknięte na kolejnych trzech
  osiach.** Rodowód stosu mieszanego (część klatek ręką, część automatem) rozróżnia teraz, CO
  automat wolno mu dotknąć, od tego, KTO naprawdę ustalił materiał — stos mieszany przestał meldować
  się jako „cała robota automatu". To samo dla wskazanej ręką kalibracji (nowy dark czy flat nie
  przepina już ogniwa, które wskazałeś) i dla przenoszenia faktów po podmianie pliku.

### Naprawione

- **Kolumna „Obiekt" mówi wprost, CZYM jest to, co pokazuje — pięć stanów zamiast jednego napisu.**
  Jeden tekst niósł dotąd dwa różne twierdzenia: „ten obiekt tak się nazywa" i „tyle mówi surowy
  nagłówek pliku" — po „Cofnij przypisanie" wiersz dalej pokazywał starą nazwę, a filtr obok już jej
  nie widział. Każdy z pięciu stanów (rozpoznany kanon, nagrobek po cofnięciu, surowe zeznanie
  nagłówka, klatka kalibracyjna, brak) ma teraz własny wygląd i własny tooltip z RECEPTĄ — gdzie
  i jak to poprawić, nie tylko z diagnozą.
- **Panel „Rodowód" przestał pokazywać wpis bez pliku.** Gdy następczyni klatki (po edycji RAW-a)
  miała już własny werdykt ręki co do materiału stosu, stary wpis w rodowodzie nie był sprzątany —
  stos liczyłby wejście klatki, której plik już nie istnieje, a panel pokazywał wiersz z pustą
  ścieżką.
- **Skan przestaje cicho połykać katalogi, do których stracił dostęp w trakcie pracy.** Zerwane
  połączenie z dyskiem sieciowym w połowie drzewa dawało przebieg z zaniżonymi liczbami i ani słowa
  o tym, że coś przepadło — nie do odróżnienia od zdrowego doskanu, w którym po prostu nic nie
  przybyło. Program (GUI i wiersz poleceń, obie drogi — zwykły skan i „Stosy") mówi teraz wprost, że
  przebieg jest niekompletny, i wypisuje które katalogi ominął; następny skan sam dobiera pominięte,
  bez żadnego dodatkowego gestu.
- **Plik z nielegalnym znakiem w nagłówku XISF przestaje znikać z archiwum.** PixInsight potrafi
  zapisać w historii przetwarzania ścieżkę źródłową z bajtem sterującym w nazwie folderu — taki
  nagłówek jest technicznie niepoprawnym XML-em, choć sam plik otwiera się bez zarzutu. Program
  czytał go wcześniej jako „kopię nieczytelną"; teraz neutralizuje niedozwolone bajty przy odczycie
  (tożsamość pliku liczy się dalej z oryginalnych, nieoczyszczonych bajtów) i klatka wraca do swoich
  sióstr z tego samego katalogu.
- **Obraz z materiału RAW przestaje słyszeć, że archiwum jest puste, gdy naprawdę ma z czego
  powstać.** Kilka obrazów dostawało zdanie „archiwum nie ma ani jednej pasującej klatki", choć
  w archiwum stały dziesiątki klatek przechodzących każdą oś zgodności — wypadały wyłącznie dlatego,
  że obraz nie miał jeszcze wskazanego odniesienia czasu, więc klatek z aparatu (czas lokalny) nie
  dało się umieścić w nocy obrazu (czas UTC). Gest naprawczy — „Wskaż odniesienie czasu…" — był przy
  tym niedostępny z tego samego, błędnego powodu. Program pokazuje teraz materiał i podpowiada
  wartość odniesienia, zamiast milczeć o obu naraz.
- **Listy przestały ucinać treść.** W kolejce przeglądu i w listwie facetów pasek przewijania obcinał
  ostatnią pozycję — w części wierszy jedyną treść, jaką miały. Wiersz po cofnięciu nazwy ma teraz
  trzy czytelne sygnały zamiast dwóch szarych słów (znacznik, wcięcie, kolor ostrzegawczy) i sortuje
  się razem z resztą swojej nazwy, nie na końcu listy.

## [0.7.0] — 2026-08-08

Wydanie o **materiale zdjęcia** — o tym, żeby program umiał powiedzieć, z czego powstał gotowy
obraz, a tam gdzie nie umie, oddał Ci głos zamiast milczeć.

Do tej pory rodowód („co weszło w ten obraz") dostawał wyłącznie ten stos, którego nagłówek sam
podał poprawne okno czasu. Reszta — a to jest jedna trzecia archiwum — pokazywała zdanie „nie wiem,
z czego powstał" i na tym się kończyło. Teraz masz **listę takich obrazów**, przy każdym **powód
i propozycję materiału**, a potwierdzenie zajmuje jedno kliknięcie. Osobno doszła cała gałąź
lustrzanki: zdjęcia z aparatu liczą czas w innym zegarze niż stos z PixInsight, więc program pyta
Cię o odniesienie zamiast udawać, że materiału nie ma.

### Dodane

- **Obrazy bez rodowodu mają wreszcie swoją listę.** W **Porządkach** doszedł wiersz
  **„Obrazy bez rodowodu"** z liczbą; klik prowadzi do **Zbiorów** z perspektywą
  **„Rodowód do potwierdzenia"**, w której widzisz dokładnie te obrazy i nic poza nimi. Do tej
  zmiany liczba istniała tylko w raporcie etapu Dostawy, a żeby trafić na konkretny obraz, trzeba
  było przeklikać całe archiwum stosów i patrzeć, który się odezwie.
  Lista **nie pokazuje obrazów, które czekają wyłącznie na przeliczenie** — jeśli nadałeś nazwę
  po ostatnim przebiegu, program wie, że jego zapis zwietrzał, i nie wysyła Cię po robotę,
  której tam nie ma.
- **Panel „Rodowód" proponuje materiał, zamiast tłumaczyć milczenie.** Przy obrazie, którego
  nagłówek nie podał sensownego okna czasu, dostajesz **klatki z tej samej nocy** — z czasem,
  ekspozycją i filtrem — i zaznaczasz, co weszło. Propozycja trzyma się tych samych osi, co dobór
  automatyczny (obiekt, filtr, teleskop, zgodna ekspozycja), więc nie jest spisem archiwum, tylko
  materiałem tego zdjęcia.
  **Gdy tej nocy nic nie ma, program to mówi i pokazuje pozostałe noce** tego obiektu z licznikami,
  ustawione od najbliższej. Wybór należy do Ciebie — tego, z której sesji powstał obraz, nie da się
  wyczytać z pliku, który o tym milczy.
- **Zestaw sprzętu (teleskop × kamera) można wskazać ręką.** Kubełek „bez zestawu" w kolejce
  przeglądu przestał być samą liczbą z notą „rozwiązywanie w przygotowaniu" — jest **klikalny**
  i otwiera okno **„Przypisz zestaw…"**, w którym jednostką wyboru jest **folder × korpus**, a nie
  pojedyncza klatka. Dotyczy to przede wszystkim zdjęć z lustrzanki przez teleskop: taki plik
  **nie ma czym zeznać o optyce** — nie ma w nim nazwy teleskopu i nigdy nie będzie, więc jedyną
  drogą jest Twoja ręka.
  **Twoje wskazanie przeżywa kolejne przebiegi** — automat je omija zamiast nadpisywać. Pomyłkę
  poprawisz drugą połową tego samego kubełka („zestaw wskazany ręką"), która otwiera to samo okno
  w trybie zmiany.
- **Odniesienie czasu dla zdjęć z lustrzanki.** Aparat zapisuje czas **lokalny**, a stos
  z PixInsight — **UTC**, więc okno rodowodu mijało własne klatki o pełne godziny i program
  meldował „nie ma pasujących klatek", mając je pod ręką. Panel „Rodowód" dostał przycisk
  **„Wskaż odniesienie czasu…"**, a program **sam podpowiada wartość**, jeśli umie ją rozpoznać
  z materiału. Po wskazaniu **od razu przelicza rodowód** — bez wędrówki na inny ekran.
- **Tolerancja czasu ekspozycji.** Suby z aparatu bywają o sekundę dłuższe niż deklaruje stos
  (90 vs 91 s). Dobór porównuje je odtąd z progiem, a nie na równość, więc materiał, który
  wcześniej wypadał bez słowa, wchodzi do rodowodu.
- **Edycja pliku RAW nie gubi już Twoich decyzji.** Programy do wywoływania (Lightroom, Camera Raw)
  dopisują swoje dane wprost do pliku `.dng`, przez co zmienia się jego tożsamość i archiwum
  widziało go jako **nową, obcą klatkę**, a stara zostawała bez pliku — razem z nazwą obiektu
  i zestawem, które jej nadałeś. Program rozpoznaje teraz podmianę, **łączy starą klatkę z nową**
  i pokazuje, które Twoje ustalenia czekają na przeniesienie. Przeniesienie jest **gestem, nie
  automatem** — przy pomyłce automat zamalowałby cudzą decyzję.
- **„Policz rodowód stosów" jako osobny etap Dostawy** — przeliczysz rodowód bez ponownego
  wczytywania całego drzewa z dysku.

### Poprawione

- **Kolumna „Ścieżka" pokazuje ścieżkę, nie samą nazwę pliku.** Nazwy z aparatu
  (`astro_dsc4198.dng`) i z PixInsight (`masterLight_BIN-1_…`) nie różnią się niczym — tożsamość
  zdjęcia niesie **folder**, a jego właśnie nie było widać. Teraz w każdym panelu drążenia widzisz
  dwa ostatnie katalogi przed nazwą.
- **Panel „Rodowód" przestał powtarzać werdykt, który zdążył zwietrzeć.** Potrafił twierdzić, że
  obraz nie ma rozpoznanego obiektu, gdy kolumna obok w tym samym oknie pokazywała jego nazwę.
  Mówi teraz wprost, że jego zapis jest starszy niż Twoja zmiana, i gdzie go odświeżyć.
- **Etap „Kalibracja" i „Rodowód stosów" nie nazywają się już tak samo.** Cztery kliknięcia
  w przycisk „Rodowód" liczyły kalibrację, a nie rodowód obrazów — nazwy są rozdzielone, a bramka
  pilnuje, żeby nie zeszły się z powrotem.

### Zmienione

- **Wydanie buduje się wyłącznie z tagu.** Plik `.exe`, który opuszcza tę maszynę, musi umieć
  powiedzieć, którą wersją jest — build zewnętrzny odmawia, gdy nie stoi na tagu, a build lokalny
  do własnych prób nie pyta o numer w ogóle.

## [0.6.0] — 2026-08-04

Wydanie o **nazywaniu obiektów ręką** — i o tym, żeby ta ręka miała gdzie się cofnąć.
Do tej pory nazwa obiektu przychodziła wyłącznie z pliku: jeśli nagłówek milczał albo mylił się,
klatka zostawała bez nazwy i nie było jak tego naprawić z programu. Teraz są cztery drogi —
nazwiesz zaznaczenie wprost, potwierdzisz propozycję z folderu, dopiszesz kartę do samego pliku
albo cofniesz własną pomyłkę — a każda z nich mówi, ile klatek ruszyła i czego nie tknęła.
Osobno: gotowe obrazy po integracji trafiają wreszcie do biblioteki razem z rodowodem („z czego
to powstało"), a program przestał milczeć przez pierwsze sekundy startu.

### Dodane
- **Nazwę obiektu można teraz nadać i COFNĄĆ prosto z ekranu „Klatki".** Do tej pory nadanie nazwy
  ręką było jednokierunkowe: pomyłkę dawało się odwrócić tylko przez edycję pliku ze słownikiem,
  i tylko dla nazw, które w nim były. Pasek zaznaczenia dostał przycisk **„Obiekt ▾"** z dwiema
  pozycjami — „Nazwij zaznaczenie…" i „Cofnij przypisanie". Obie działają **wyłącznie na tym, co
  masz zaznaczone**, nigdy na całej widocznej liście; przy pustym zaznaczeniu są wygaszone.
  **Program chroni to, czego nie powinien ruszać, i mówi o tym wprost.** Cofnięcie zdejmuje tylko
  nazwy, które postawiła Twoja ręka albo folder — **nazwa odczytana z nagłówka pliku albo z pozycji
  na niebie zostaje**, bo to fakt z archiwum, a nie pomyłka do naprawienia. Oba gesty pomijają
  kalibrację (dark, flat, bias — te obiektu nie mają z definicji).
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
  potrafi zebrać setki klatek z kilkudziesięciu różnych katalogów — a nazwę nadaną ręką **cofniesz
  w „Klatki" przez „Obiekt ▾ → Cofnij przypisanie"**. Przy pustym zaznaczeniu przycisk jest wygaszony.
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
- **Szukajka obiektów znajduje po KAŻDEJ nazwie, jaką obiekt nosi — i nie czepia się kropek ani
  spacji.** Wpisz „Large Magellanic Cloud", a znajdziesz kubełek `LMC`; wpisz „M 42" ze spacją,
  a znajdziesz `M42`; „sh2 155" znajdzie `Sh2-155`. Do tej pory pole porównywało wpisany tekst
  znak w znak z nazwą na liście, więc trafiało tylko wtedy, gdy pisałeś dokładnie tak, jak nazwa
  jest zapisana w katalogu — a nazwy potocznej nie znajdowało w ogóle, bo `LMC` nie ma z frazą
  „Large Magellanic Cloud" ani jednej wspólnej litery.
- **Katalog `_SOLAR` i `_COMETS` przestał być ślepym zaułkiem.** Zdjęcia Księżyca, Jowisza
  i komety 21P leżą o poziom głębiej niż zwykłe cele — program to teraz rozumie i nazywa je
  tak samo jak resztę.

### Zmienione
- **Gotowy obraz po integracji można teraz nazwać I cofnąć tak samo jak każdą inną klatkę.** Do tej
  pory „Nazwij zaznaczenie…" go obejmowało, a „Cofnij przypisanie" już nie — więc dało się nadać
  stosowi nazwę i zostać z nią na zawsze: żaden ekran nie umiał tego odwrócić. Teraz oba gesty
  obejmują stosy, a zdanie po geście mówi, ile ich ruszyłeś („w tym gotowe obrazy: 2") — bo to
  jedyna klatka, przy której nazwa sięga powiązania ze zdjęciami, z których obraz powstał.
  Powiązanie potwierdzone plikiem albo Twoją ręką **przeżywa** taki gest; powiązanie zwykłe,
  dobrane z okna czasu, przelicza się uczciwie — stos bez obiektu okna nie ma z definicji.
- **Klatka, której zdjąłeś nazwę, jest w kolejce przeglądu widoczna jako TWÓJ WERDYKT.** Wracała do
  tego samego wiersza co klatki, o których nikt nic nie powiedział, i wyglądała identycznie — a
  „Przypisz obiekt…" po cichu jej nie tykało, bo program chroni cofnięcie przed przypadkowym
  odwróceniem. Dostawałeś „przypisano 5 z 8" bez wyjaśnienia. Teraz takie klatki mają w kolejce
  własny wiersz z dopiskiem **„cofnięte ręką"**, a przycisk przy nim działa i mówi wprost, że
  przypisanie nadpisze wcześniejszy werdykt — **mówi to również samo okno zapisu, zanim klikniesz**,
  a nie dopiero w dymku nad przyciskiem.
- **Dopisek „cofnięte ręką" mają teraz WSZYSTKIE cztery wiersze kolejki, nie dwa z nich.** Wcześniej
  dostały go pozycje z nazwą w nagłówku i kubełek zdjęć z lustrzanki (RAW), a dwa pozostałe —
  „bez nazwy w nagłówku" i „gotowe obrazy" — nie. Klatka, której zdjąłeś nazwę odczytaną z pozycji
  na niebie albo z folderu, wracała więc do wspólnego wiersza **nieodróżnialna od klatki, o której
  nikt nigdy nie decydował**; przy gotowych obrazach ta droga jest osiągalna jednym kliknięciem,
  odkąd „Obiekt ▾" obejmuje stosy. Teraz każda z tych populacji ma własny wiersz z dopiskiem
  i **otwiera dokładnie tę listę, którą pokazuje jej licznik**. To ostatnie nie jest kosmetyką:
  kliknięcie w „cofnięte ręką" otwierało dotąd okno „Napraw nagłówek…" z klatkami **nietkniętymi**
  — czyli akcja pisząca do PLIKÓW archiwum celowała w grupę rozłączną z tą, którą widziałeś pod
  spodem. Przycisk nad takim wierszem jest aktywny i mówi wprost, że dopisanie karty `OBJECT`
  zastąpi Twój werdykt nazwą, którą wpiszesz — bo tak właśnie działa i to jedyna droga, którą
  cofnięcie gaśnie.
  Raport Dostawy podaje przy okazji, ile z nierozpoznanych klatek to Twoja decyzja, a ile brak
  wiedzy — te pierwsze zostają w procencie rozpoznania świadomie, bo inaczej odrzucenie nazwy
  podnosiłoby wynik. **Liczby są dwie i każda stoi przy swoim zdaniu**: osobno klatki, które nazwę
  w nagłówku mają, osobno te bez niej. Jedna wspólna liczba potrafiła dopisać „z tego cofnięte
  ręką: 16" do wiersza pokazującego zero.
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
- **Program mówi teraz, co robi, zamiast stać nieruchomo.** Uruchomienie na pełnym archiwum
  trwało kilka sekund, przez które **na ekranie nie było nic** — okno pojawiało się dopiero po
  wczytaniu wszystkiego, więc jedynym sygnałem życia był kursor. Teraz okno staje **od razu**
  i pisze, na czym stoi: „Otwieram bazę…", „Buduję widoki…". Tak samo przy dłuższych operacjach
  w trakcie pracy — odświeżaniu widoków po etapie i zapisie nazw, gdzie dochodzi licznik
  („Zapisuję nazwy: 12 z 34"). Opis znika, gdy robota się kończy, i **nie zasłania komunikatu
  o jej wyniku** — to dwa osobne miejsca na pasku.
- **Zaznaczenie wszystkich klatek przestało zamrażać okno.** Na archiwum kilkunastu tysięcy zdjęć
  `Ctrl+A` i zaznaczanie myszą blokowały ekran na ponad dwie sekundy — przy przeciąganiu myszą
  za każdym ruchem. Program przechodził wtedy po zaznaczeniu dwa razy i pytał tabelę o każdą
  komórkę z osobna. Teraz robi to raz i bierze same numery wierszy: **te same dwie sekundy zeszły
  do setnych części sekundy**. Zaznaczenie działa dokładnie tak samo — sprawdzone porównaniem
  starej i nowej drogi, łącznie z zaznaczeniem nieciągłym i przy włączonym grupowaniu.
- **Wiersze kolejki przeglądu, w które nie da się wejść, tłumaczą się zamiast milczeć.** Kliknięcie
  w wiersz z samym licznikiem (np. „config-review: 433 · bez nagłówka: 1") nie dawało **żadnej**
  reakcji — ani podświetlenia, ani komunikatu — więc wyglądało jak zawieszenie programu. Teraz
  taki wiersz mówi, czego jest opisem i dlaczego nie prowadzi dalej; ta sama treść jest pod
  kursorem jako podpowiedź.
- **Wygaszone przyciski mówią, czego im brakuje.** „Napraw nagłówek…" był szary bez słowa
  wyjaśnienia przy każdym wierszu kolejki, a „Obiekt ▾" — przy zaznaczeniu klatek, których nazwa
  pochodzi z nagłówka (czyli przy większości zdjęć w archiwum). Każdy z nich podaje teraz
  **drogę właściwą dla tego, co zaznaczyłeś**: gdzie tę nazwę się poprawia i którym gestem.
  Gdy przycisk jest aktywny, podpowiedź mówi z góry, ilu klatek gest dotknie.
- **Powiązanie gotowego obrazu ze zdjęciami, z których powstał, przestało ginąć po nazwaniu albo
  cofnięciu nazwy.** Program czyta z pliku stosu listę zdjęć, które do niego weszły — to najmocniejszy
  dowód, jaki ma. Gdy jednak zmieniłeś nazwę obiektu któremuś ze zdjęć, następny przebieg „Stosy"
  przeliczał okno od nowa, nie znajdował w nim tego zdjęcia i **kasował całe udowodnione powiązanie**,
  podmieniając je na „nie wiem, z czego to powstało". Chroniony był tylko przypadek, w którym pliku
  stosu nie dało się przeczytać — czyli akurat ten, w którym plik leżał poza zasięgiem. Teraz program
  porównuje SIŁĘ dowodów: zapisane powiązanie potwierdzone plikiem albo Twoją ręką **przeżywa
  przebieg**, który umie powiedzieć mniej. Powiązanie zwykłe (dobrane z okna czasu) dalej aktualizuje
  się normalnie, więc rodowód nie zastyga. Raport przebiegu mówi wprost, ile rodowodów zostawiono
  nietkniętych i **dlaczego** — osobno „archiwum odłączone", osobno „zapisany dowód mocniejszy".
- **„Cofnij przypisanie" mówiło o nagłówku przy klatce, która żadnego nie miała.** Program liczył
  jednym workiem dwa zupełnie różne powody pominięcia: „ta klatka nazwy w ogóle nie miała, więc nie
  było czego cofać" oraz „nazwę postawił nagłówek pliku albo pozycja na niebie, a tych ręka nie
  zdejmuje". Dostawałeś „cofnięto 2 z 3 · z nagłówka/regionu: 1" i podpowiedź, żeby naprawić kartę
  w pliku — przy klatce, w której nie było czego naprawiać. Teraz są to dwa osobne człony zdania.
- **Zapis z kolejki przeglądu milczał o tym, że dotknął gotowego obrazu.** Ten sam gest wykonany
  z ekranu „Klatki" mówił „w tym gotowe obrazy: 2", a wykonany z kolejki — nic, choć to właśnie
  kolejka jest naturalną drogą do takiej klatki. Nazwanie gotowego obrazu jest jedynym zapisem
  nazwy, który sięga powiązania ze zdjęciami źródłowymi, więc przechodził bez śladu.
- **Podsumowanie gestu na osi obiektu było niewidoczne dokładnie wtedy, gdy coś zapisano.** Zdanie
  z rozbiciem („nazwano 4 z 8 · kalibracja: 2 · z nagłówka: 2") padało chwilę przed odświeżeniem
  listy, a odświeżenie natychmiast zastępowało je własnym „Wczytano N klatek". Widziałeś je więc
  wyłącznie po geście, który niczego nie zmienił. Teraz pada jako ostatnie.
- **Okno nazywania opisywało zaznaczenie cudzym zdaniem i obiecywało więcej, niż robiło.** Wywołane
  z paska „Klatki" mówiło „N klatek bez nazwy w metadanych (format bez karty OBJECT)" — o klatkach,
  które nazwę mają (z folderu) i bywają plikami FITS z kartą `OBJECT`. Przycisk liczył przy tym całe
  zaznaczenie, więc obiecywał „Przypisz 8 klatek" i zapisywał 4. Teraz okno mówi, ile klatek naprawdę
  ruszy, **ile nazw przemaluje** i ile zostawi nietkniętych — zanim klikniesz.
- **Odmowa przy niejednorodnym zaznaczeniu podawała zmyśloną liczbę.** Komunikat zawsze mówił „2 różne
  obiekty", także gdy było ich pięć — więc zawężenie zaznaczenia do dwóch kończyło się tą samą odmową.
  Teraz liczba jest prawdziwa.
- **Licznik zadań w bocznym pasku nie zauważał gestu, który go zmieniał** — pokazywał stan sprzed
  nazwania albo cofnięcia aż do wejścia w „Porządki". Teraz odświeża się razem z resztą.
- **Przycisk „Anuluj" w oknie przypisania był po angielsku.**
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

[Niewydane]: https://github.com/abo-t/horreum/compare/v0.23.0...HEAD
[0.23.0]: https://github.com/abo-t/horreum/compare/v0.22.0...v0.23.0
[0.22.0]: https://github.com/abo-t/horreum/compare/v0.21.0...v0.22.0
[0.21.0]: https://github.com/abo-t/horreum/compare/v0.20.0...v0.21.0
[0.20.0]: https://github.com/abo-t/horreum/compare/v0.19.0...v0.20.0
[0.19.0]: https://github.com/abo-t/horreum/compare/v0.18.0...v0.19.0
[0.18.0]: https://github.com/abo-t/horreum/compare/v0.17.0...v0.18.0
[0.17.0]: https://github.com/abo-t/horreum/compare/v0.16.0...v0.17.0
[0.16.0]: https://github.com/abo-t/horreum/compare/v0.15.0...v0.16.0
[0.15.0]: https://github.com/abo-t/horreum/compare/v0.14.0...v0.15.0
[0.14.0]: https://github.com/abo-t/horreum/compare/v0.13.0...v0.14.0
[0.13.0]: https://github.com/abo-t/horreum/compare/v0.12.0...v0.13.0
[0.12.0]: https://github.com/abo-t/horreum/compare/v0.11.0...v0.12.0
[0.11.0]: https://github.com/abo-t/horreum/compare/v0.10.0...v0.11.0
[0.10.0]: https://github.com/abo-t/horreum/compare/v0.9.1...v0.10.0
[0.9.1]: https://github.com/abo-t/horreum/compare/v0.9.0...v0.9.1
[0.9.0]: https://github.com/abo-t/horreum/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/abo-t/horreum/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/abo-t/horreum/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/abo-t/horreum/compare/v0.5.1...v0.6.0
[0.5.1]: https://github.com/abo-t/horreum/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/abo-t/horreum/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/abo-t/horreum/compare/v0.3.2...v0.4.0
[0.3.2]: https://github.com/abo-t/horreum/compare/v0.3.1...v0.3.2
[0.3.1]: https://github.com/abo-t/horreum/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/abo-t/horreum/compare/v0.2...v0.3.0
[0.2]: https://github.com/abo-t/horreum/compare/v0.1...v0.2
[0.1]: https://github.com/abo-t/horreum/releases/tag/v0.1
