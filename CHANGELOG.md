# Historia zmian

Format wzorowany na [Keep a Changelog](https://keepachangelog.com/pl/1.1.0/).
Wersjonowanie [semantyczne](https://semver.org/lang/pl/). Projekt jest we wczesnym rozwoju —
schemat i API mogą się jeszcze zmieniać.

## [Niewydane]

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

[Niewydane]: https://github.com/abo-t/horreum/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/abo-t/horreum/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/abo-t/horreum/compare/v0.3.2...v0.4.0
[0.3.2]: https://github.com/abo-t/horreum/compare/v0.3.1...v0.3.2
[0.3.1]: https://github.com/abo-t/horreum/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/abo-t/horreum/compare/v0.2...v0.3.0
[0.2]: https://github.com/abo-t/horreum/compare/v0.1...v0.2
[0.1]: https://github.com/abo-t/horreum/releases/tag/v0.1
