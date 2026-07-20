# Historia zmian

Format wzorowany na [Keep a Changelog](https://keepachangelog.com/pl/1.1.0/).
Wersjonowanie [semantyczne](https://semver.org/lang/pl/). Projekt jest we wczesnym rozwoju —
schemat i API mogą się jeszcze zmieniać.

## [Niewydane]

### Dodane
- **Rozpoznawanie kompleksów po współrzędnych.** Obiekty rozciągłe, które nie mają jednego numeru
  katalogowego — jak kompleks Veil, czyli Pętla Łabędzia (NGC6960 + NGC6979 + NGC6992 + NGC6995) —
  są teraz rozpoznawane po tym, **gdzie celował teleskop**, a nie po nazwie w nagłówku. W archiwum
  zdejmuje to z listy „do przeglądu" 250 klatek, w tym **83, którym program zapisujący nie wpisał
  żadnej nazwy** — rozpoznanie po nazwie nie miało jak ich złapać. Rozpoznawalność obiektów na
  klatkach światła: 97,2% → 99,0%. Definicje kompleksów są danymi
  (`horreum/resolve/data/regions.json`), więc kolejny dopisuje się bez zmiany kodu.

  Zachowawczo z założenia: **nazwa z nagłówka zawsze wygrywa ze współrzędnymi** — klatki podpisane
  „NGC6992" zostają przy NGC6992, choć leżą wewnątrz kompleksu. Klatka celowana w pojedynczy obiekt,
  ale bez podpisu, zostaje w przeglądzie, zamiast dostać zgadywany numer katalogowy. Ręczne
  przypisanie obiektu, gdy powstanie, będzie miało pierwszeństwo przed rozpoznaniem ze współrzędnych.

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

[Niewydane]: https://github.com/abo-t/horreum/compare/v0.3.2...HEAD
[0.3.2]: https://github.com/abo-t/horreum/compare/v0.3.1...v0.3.2
[0.3.1]: https://github.com/abo-t/horreum/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/abo-t/horreum/compare/v0.2...v0.3.0
[0.2]: https://github.com/abo-t/horreum/compare/v0.1...v0.2
[0.1]: https://github.com/abo-t/horreum/releases/tag/v0.1
