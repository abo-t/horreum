# Horreum — instrukcja obsługi

*Dla osoby, która pobrała Horreum z GitHuba i chce zapanować nad własnym archiwum astrofoto —
bez znajomości programowania. Przeprowadzi Cię od pustej bazy, przez pierwsze wczytanie zdjęć,
po nazwanie sprzętu i obiektów, przeglądanie zbiorów i planowanie kolejnych sesji. Operacje, które
zmieniają pliki na dysku (zmiana nazw z faktów, budowa drzewa pod WBPP), są tu tylko wskazane —
mają dostać własny opis; tutaj budujemy fundament.*

---

## Zanim zaczniesz — o co w tym chodzi

Wyobraź sobie **bibliotekarza**, który nie przestawia Twoich książek, tylko robi im **katalog**.
Horreum działa dokładnie tak z Twoimi klatkami FITS i XISF:

- **Twoje pliki zostają tam, gdzie są.** Horreum ich nie przenosi, nie zmienia nazw i nie kasuje.
  Czyta tylko **nagłówek** każdego pliku (dane, które zapisał program akwizycyjny) i wpisuje je do katalogu.
- **Katalog to jeden plik `.db`** — Twoja baza. To ona jest źródłem prawdy, nie układ folderów.
  Możesz mieć jedną bazę na całe archiwum.
- **Tożsamością klatki jest jej zawartość, nie nazwa ani ścieżka.** Gdy przeniesiesz albo przemianujesz
  plik i zeskanujesz go ponownie, Horreum rozpozna, że to ta sama klatka — nie zrobi duplikatu.
- **Nic się nie nadpisuje.** Każda zmiana to dopisek do historii, więc zawsze widać, co i kiedy się stało.

Horreum sam wyprowadza z nagłówków **trzy osie**, po których szukasz zdjęć:

- **Teleskop** — jakim sprzętem robione (z pola `TELESCOP`),
- **Stanowisko** — skąd obserwowane (ze współrzędnych GPS w nagłówku),
- **Obiekt** — co na zdjęciu (rozpoznaje katalogi: Messier, NGC, IC, nazwy potoczne, ciała Układu Słonecznego).

Twoja rola sprowadza się do dwóch rzeczy: **nadać sprzętowi i miejscom czytelne nazwy** oraz
**rozstrzygnąć nieliczne przypadki**, których automat nie był pewny. Reszta dzieje się sama.

Droga, którą przejdziesz w tej instrukcji:

    1. Uruchom program          (pobrany plik albo ze źródła)
    2. Załóż bazę               (Plik -> Nowa baza)
    3. Przyjmij pierwszą dostawę (Dostawa -> Przyjmij nowe)
    4. Uporządkuj               (Porzadki -> nazwij teleskopy, stanowiska i obiekty)
    5. Przeglądaj               (Zbiory -> perspektywy)
    6. Zaplanuj                 (Planer -> co warto zrobic dzis)

Kroki 1–5 przechodzisz po kolei, raz. Krok 6 jest osobny — możesz do niego wrócić kiedykolwiek.

---

## Wersja gotowa (`.exe`) czy ze źródła?

**Jedno pytanie:** czy masz Windows i chcesz po prostu kliknąć, żeby ruszyło?

| | Kiedy tak | Co robisz |
|---|---|---|
| **Wersja gotowa** (zalecana) | Masz Windows, nie chcesz nic instalować | Pobierasz **jeden plik `.exe`** z **Releases** i klikasz go dwa razy |
| **Ze źródła** | Masz Linux/Mac, albo chcesz najnowszy kod / własne zmiany | Instalujesz Pythona i uruchamiasz komendą |

Koszt pomyłki jest zerowy — obie wersje działają na tej samej bazie. Jeśli wahasz się, wybierz
**wersję gotową**. Opis obu jest w Kroku 1.

---

## Mapa ekranu

Po uruchomieniu widzisz jedno okno. Z lewej pasek z **czterema miejscami**, reszta to bieżący widok:

    Menu:  Plik            Widok
           |                |
           Otworz/Nowa      Ciemny/Jasny
           baza

    +-----------+------------------------------------------+
    | Dostawa   |   <- Krok 3: wczytujesz tu nowe zdjęcia   |
    | Zbiory    |   <- Krok 5: przegladasz katalog          |
    | Porzadki  |   <- Krok 4: nazywasz sprzet, przeglad    |
    | Planer    |   <- Krok 6: co warto sfotografowac dzis  |
    +-----------+------------------------------------------+

- **Dostawa** — tu wpuszczasz nowe zdjęcia do katalogu.
- **Zbiory** — biblioteka wszystkich klatek; filtrujesz i układasz „perspektywami".
- **Porządki** — lista rzeczy do zrobienia (nienazwany sprzęt, klatki bez obiektu) i osie
  Teleskop / Stanowisko / Obiekt. Cyfra przy nazwie, np. **Porządki (3)**, mówi, ile zadań czeka.
- **Planer** — co da się sfotografować z Twojego stanowiska i ile materiału już masz.

Pierwsze trzy miejsca to droga Twojego archiwum: **wpuść → uporządkuj → przeglądaj**. Czwarte
patrzy w przód, a nie wstecz, więc możesz je poznać później — działa dopiero, gdy w bazie coś jest.

---

## Krok 1 — Uruchom program

### Wersja gotowa (Windows)

1. Wejdź na stronę projektu na GitHubie, w zakładkę **Releases**.
2. Pobierz plik **`Horreum-<wersja>-windows-x64.exe`** — to jedyny plik w sekcji „Assets".
3. Zapisz go, gdzie Ci wygodnie (pulpit, folder z astrofoto, pendrive) i **kliknij dwa razy**.

Nic nie instalujesz i nic nie rozpakowujesz — cały program siedzi w tym jednym pliku. Możesz go
przenosić i kopiować dowolnie; nie ma żadnego folderu, który musiałby leżeć obok.

> **Pierwsze uruchomienie trwa dłużej — i tak ma być.** Program rozpakowuje się w pamięci, więc
> zanim pojawi się okno, mija kilka sekund. Okno od razu mówi, co robi („Otwieram bazę…",
> „Buduję widoki…") — jeśli coś pisze, to pracuje, a nie zawiesiło się.
>
> Windows przy pierwszym uruchomieniu może ostrzec, że to nieznana aplikacja — to normalne dla
> programów spoza sklepu; wybierz **Więcej informacji → Uruchom mimo to**.
>
> **Którą wersję mam?** Numer stoi w **tytule okna**, np. „Horreum 0.6.0".

### Ze źródła (każdy system)

Potrzebujesz Pythona 3.9 lub nowszego. W terminalu, w folderze projektu:

```bash
pip install -e ".[gui]"
python -m horreum.gui
```

Okno wygląda i działa identycznie jak wersja gotowa.

---

## Krok 2 — Załóż bazę

Baza to pojedynczy plik `.db` — Twój katalog. Zakładasz go **raz**; potem tylko go otwierasz.

1. Menu **Plik → Nowa baza…**
2. Wskaż miejsce i nazwę pliku — np. `astro.db` w wybranym folderze.

| Pole | Co wpisać |
|---|---|
| **Nazwa pliku** | krótko, bez spacji: np. `astro.db` |
| **Miejsce** | gdzie łatwo trafisz — pulpit albo folder z astrofoto |

**Co system zrobi sam:** utworzy pusty plik i przygotuje go do pracy (założy wewnętrzną strukturę).
Od tej chwili nazwa bazy jest widoczna, a miejsca w pasku bocznym się odblokowują.

> Bazę zakładasz **pustą** — to normalne, że po tym kroku nic w niej nie ma. Zdjęcia wpuścisz w Kroku 3.
> Gdy następnym razem otworzysz program, sam wróci do ostatnio używanej bazy — nie musisz jej szukać.
> Chcesz później wrócić do tej bazy ręcznie? **Plik → Otwórz bazę…**

---

## Krok 3 — Przyjmij pierwszą dostawę

To jest pierwsza konfiguracja: pokazujesz Horreum, gdzie leżą Twoje zdjęcia, a on buduje z nich katalog.

1. Wejdź w miejsce **Dostawa** (pasek boczny).
2. Kliknij dużą złotą akcję **Przyjmij nowe  (skan → grupuj → rozwiąż → kalibracja → delta)**.
3. Przy **pierwszym** uruchomieniu program zapyta o folder — wskaż **główny katalog z astrofoto**
   (może zawierać dowolnie zagnieżdżone podfoldery; Horreum zejdzie w głąb sam).
4. Poczekaj. Pasek postępu i licznik pokazują, ile plików już przeszło. Duże archiwa idą minutami —
   to jednorazowy koszt.

**Co oznaczają etapy** (Horreum robi je po kolei, jednym kliknięciem):

| Etap | Co się dzieje |
|---|---|
| **skan** | czyta nagłówki plików i wpisuje klatki do katalogu (nic nie zmienia na dysku) |
| **grupuj** | wyprowadza osie teleskopu i konfiguracji sprzętu |
| **rozwiąż** | rozpoznaje obiekty (NGC/Messier/…), stanowiska (GPS) i filtry |
| **kalibracja** | dobiera przepisy kalibracji i wiąże klatki z masterami |
| **delta** | podsumowuje: ile obiektów rozpoznano, co zostało do ręcznej decyzji |

Gdy skończy, na dole zobaczysz podsumowanie — np. ile klatek przyszło, ile było nowych, ile
rozpoznanych obiektów. Cyfra przy **Porządki** podpowie, ile rzeczy warto dokończyć ręcznie.

> **To bezpieczne.** Skan tylko **czyta** Twoje pliki — nigdy ich nie przesuwa, nie przemianowuje
> ani nie kasuje. Możesz go uruchamiać wielokrotnie bez obaw.

> **Kolejne dostawy są szybsze.** Przy następnym imporcie Horreum pomija pliki, które już zna
> (rozpoznaje je po zawartości), i dopisuje tylko nowe. Wystarczy znów **Przyjmij nowe** — zapamięta
> ostatni folder.

**Tryb zaawansowany** (sekcja niżej na tym samym ekranie) przyda się, gdy chcesz wskazać **inny**
folder niż zapamiętany albo puścić etapy pojedynczo (**Skanuj**, **Grupuj**, **Rozwiąż**,
**Pokaż deltę**). Pole **poziom** pozwala oznaczyć, czy to archiwum (**zimny (archiwum)**) czy dysk
roboczy — dla zwykłego przeglądu zostaw **—**. Na co dzień wystarcza złota **Przyjmij nowe**.

### Stosy — gotowe obrazy po integracji

Na dole ekranu **Dostawa** jest osobna sekcja **Stosy**. Twoje archiwum to pojedyncze klatki
z teleskopu; gotowe obrazy po złożeniu (integracji) leżą gdzie indziej — w drzewie obróbki.
Kliknij **Wciągnij stosy…**, wskaż korzeń tego drzewa, a Horreum doda te obrazy do biblioteki.

Co dokładnie bierze: **wyłącznie pliki `masterLight*.xisf`**, czyli wynik integracji, razem
z jego wariantami obrazu - skadrowanym (`_autocrop`) i przeskalowanym (`_drizzle_1x`). Pomija
kolejne kroki obróbki: po usunięciu gradientu (`_ABE`, `_DBE`), po kalibracji koloru (`_SPCC`),
bez gwiazd (`_starless`) i podobne - także doklejone do wariantu (`_autocropSPCC`). To nie są
osobne zdjęcia, tylko dalsza obróbka jednego obrazu.

> **To bezpieczne — i osobne.** Ta droga tylko **czyta**: w drzewie obróbki nie zmienia się ani
> jeden bajt. Nie wchodzi też do **Przyjmij nowe** — codzienna dostawa dotyczy archiwum, a po
> stosy sięgasz osobno, kiedy chcesz. Folder jest zapamiętywany, więc następnym razem okno wyboru
> otworzy się od razu we właściwym miejscu.

Jeśli gotowy obraz nie ma w nagłówku nazwy obiektu, pojawi się o tym wiersz w **Porządkach** —
i **da się z niego wejść i naprawić**: gotowy obraz nazywa się dokładnie tak samo jak każda inna
klatka (Krok 4). Wiersz mówi, ile obrazów nie wie, co przedstawia, a klik prowadzi do listy.

**Horreum zapisuje też, z czego ten obraz powstał.** Dla każdego wciągniętego stosu szuka w bazie
klatek, które do niego weszły, i wiąże je z nim — dzięki temu widzisz, ile godzin naprawdę siedzi
w gotowym obrazie, a nie tylko ile klatek masz na dysku. To powiązanie zobaczysz w panelu
**Rodowód…** (Zbiory, po zaznaczeniu obrazu).

---

## Krok 4 — Uporządkuj: nadaj nazwy i przejrzyj wątpliwości

Wejdź w **Porządki**. Zobaczysz listę zadań ze stanu bazy — każde z liczbą i strzałką `›`:

| Zadanie | Co znaczy i co zrobić |
|---|---|
| **Klatki bez obiektu** | Automat nie rozpoznał, co na zdjęciu. Kliknij, żeby zobaczyć te klatki (na razie podgląd). |
| **Teleskopy bez etykiety** | Sprzęt ma tylko techniczną nazwę z nagłówka. Nadaj mu swoją. |
| **Stanowiska bez nazwy** | Miejsca obserwacji mają tylko współrzędne. Nazwij je („Dom", „Bieszczady"). |
| **Duplikaty (>1 kopia)** | Klatki, których masz więcej niż jedną kopię. Klik prowadzi do Zbiorów. |

Dwie pozycje są **wyszarzone** — to tylko informacja, nie zadania: **XISF (nagłówki tylko do
odczytu)** oraz **Zniknięte z dysku**. Nie klikają się nigdzie.

### Nazwij teleskop

1. W Porządkach kliknij **Teleskopy bez etykiety ›** — wejdziesz w **Oś teleskopu**.
2. Na liście **Aktywne teleskopy (kanoniczne)** dwuklik w kolumnę **Etykieta** przy wybranym sprzęcie
   i wpisz swoją nazwę (np. `Newton 8"`). Zatwierdź Enterem.
3. Gdy ten sam teleskop występuje pod dwiema technicznymi nazwami — zaznacz jeden wiersz, w polu
   **Scal zaznaczony w:** wybierz drugi i kliknij **Scal**. Pomyłkę cofniesz przyciskiem
   **Cofnij scalenie**.
4. Wróć strzałką **← Porządki**.

### Nazwij stanowisko

Tak samo, przez **Stanowiska bez nazwy ›** (**Oś obserwatorium**): dwuklik w kolumnę **Nazwa**,
wpisz nazwę miejsca. Dwa zapisy tego samego miejsca (np. minimalnie różne GPS domu) łączysz **Scal**.

> Nazwy i scalenia są **odwracalne** — dlatego program nie pyta „czy na pewno?". Zawsze możesz
> poprawić: zmienić etykietę albo kliknąć **Cofnij scalenie**.

### Przejrzyj obiekty — i nazwij to, czego automat nie rozpoznał

**Klatki bez obiektu ›** otwiera **Przegląd obiektów**: z lewej biblioteka rozpoznanych obiektów,
pod nią **Kolejka przeglądu** — lista tego, co czeka na Twoją decyzję. Klik w wiersz kolejki
pokazuje po prawej te konkretne klatki.

**Kolejka nie jest jedną listą — to kilka kubełków, bo drogi naprawy są różne.** Wiersz mówi, ile
klatek zawiera i czego potrzebuje:

| Wiersz kolejki | Co znaczy | Czym to naprawiasz |
|---|---|---|
| nazwa obiektu, np. **`FlatWizard · 12 klatek`** | nagłówek ma nazwę, ale program jej nie rozpoznaje | **Przypisz obiekt…** — wskazujesz, co to naprawdę jest |
| **bez nazwy w nagłówku** | plik nic nie mówi o obiekcie | **Napraw nagłówek…** — nazwa idzie do **pliku** |
| **bez nazwy, format bez karty (RAW)** | zdjęcie z lustrzanki; ten format nie ma gdzie zapisać nazwy | **Przypisz obiekt…** — nazwa idzie do bazy |
| **bez nazwy, gotowe stosy** | obraz po integracji bez nazwy | **Napraw nagłówek…**, tak samo jak klatki |
| **…z tego ze ścieżki** | folder podpowiada nazwę, program czeka na Twoje „tak" | **Zatwierdź ze ścieżki…** |
| dopisek **`· cofnięte ręką`** | to Twoja własna decyzja, nie brak wiedzy — sam zdjąłeś tu nazwę | zależy od kubełka; program uprzedzi, że nadpisze Twój werdykt |

**Wygaszony przycisk zawsze tłumaczy się sam** — najedź na niego myszą, a powie, czego mu brakuje
albo która droga jest właściwa dla zaznaczonego wiersza. Nie musisz zgadywać.

#### Nazwij klatki ręką

1. Kliknij wiersz kolejki — po prawej pojawią się jego klatki, **wszystkie zaznaczone**.
2. Jeśli chcesz nazwać tylko część — przytnij zaznaczenie (klik, `Ctrl`, `Shift`).
3. Kliknij **Przypisz obiekt…**, wpisz lub wybierz nazwę, zatwierdź.

Okno daje dwie drogi — wybierasz jedną:

| Pole | Co zrobić |
|---|---|
| **Istniejący obiekt:** | rozwiń listę i wskaż obiekt, który już jest w bibliotece |
| **albo nowa nazwa** | wpisz nazwę, jak ją znasz: `IC 1795`, `LMC`, `Księżyc`, `C/2023 A3` |

Wypełnione pole nazwy **nadpisuje** wybór z listy. Gdy podasz nową nazwę, program zapamięta ją jako
**alias**: kolejne klatki z tym zapisem w nagłówku rozpozna już sam, bez pytania.

**Zapisujesz to, co masz ZAZNACZONE** — nigdy całą widoczną listę. Po zapisie dostajesz zdanie
z rozbiciem: ile klatek zmieniono i **dlaczego resztę pominięto** (osobno kalibrację, osobno klatki
z nagłówka, osobno te, które zmieniły się w międzyczasie).

> Nazwa spoza katalogów też jest przyjmowana. `LMC` czy `Księżyc` nie mają numeru NGC — program
> zapamięta je jako **obiekt własny** i od tej pory będzie je rozpoznawał sam.

#### Potwierdź nazwy podpowiedziane przez foldery

Jeśli trzymasz zdjęcia w folderach nazwanych obiektami (`…\NGC6960\…`), program to widzi i **proponuje** —
ale nigdy nie zapisuje sam, bo folder bywa śmietnikiem. Kliknij **Zatwierdź ze ścieżki…**: dostaniesz
listę propozycji pogrupowanych po nazwie, z liczbą klatek przy każdej. Odznacz te, których nie chcesz,
i zatwierdź resztę.

> **Nagłówek jest ważniejszy niż folder.** Gdy plik sam mówi, co przedstawia, program wierzy jemu —
> propozycja z folderu dotyczy tylko klatek, które milczą.

#### Wpisz nazwę do samego pliku

**Napraw nagłówek…** to jedyna droga, która **zmienia Twoje pliki** — dopisuje im kartę `OBJECT`,
żeby nazwa została w archiwum na zawsze, także dla innych programów.

> ⚠ **To zapis na dysku.** Okno najpierw pokazuje pełną listę plików i dokładną nazwę, która do nich
> pójdzie — przeczytaj ją przed zatwierdzeniem. Każdy zapis ma **kopię zapasową nagłówka**, więc
> istnieje **Cofnij**; program przy tym nigdy nie rusza samego zdjęcia, tylko jego opis.

#### Nazwij albo cofnij wprost ze Zbiorów

Nie musisz iść przez kolejkę. W **Zbiory** zaznacz dowolne klatki i użyj **Obiekt ▾**:

- **Przypisz obiekt…** — to samo okno co wyżej,
- **→ NAZWA** — skrót do nazw, których użyłeś ostatnio: przypisuje od razu, bez okna,
- **Cofnij przypisanie** — zdejmuje nazwę, którą postawiła Twoja ręka albo folder.

> **Cofnięcie nie kasuje faktów z plików.** Nazwa odczytana z nagłówka albo z pozycji na niebie
> **zostaje** — bo to fakt z archiwum, nie Twoja pomyłka. Cofnięcie zostaje też cofnięciem:
> klatka nie dostanie nazwy z powrotem przy najbliższym **Rozwiąż**, tylko wróci do kolejki
> i poczeka na Twoją decyzję.

---

## Krok 5 — Przeglądaj zbiory

Wejdź w **Zbiory** — to widok wszystkich klatek z filtrem. Najprościej korzystać z gotowych
**perspektyw** (rozwijana lista u góry):

| Perspektywa | Pokazuje |
|---|---|
| **Przegląd** | wszystkie klatki |
| **Kalibracja** | klatki kalibracyjne (bias/dark/flat) |
| **Duplikaty** | tylko klatki mające więcej niż jedną kopię |
| **Do przeglądu** | to, co czeka na ręczną decyzję |

Panel **Pola (kolumny)** z lewej pozwala dołożyć kolumny (Obiekt, Filtr, Kamera…). Własne ułożenie filtrów
zapiszesz przyciskiem **★ Zapisz widok** jako nową perspektywę — zapisane widoki **siedzą w bazie**,
więc jadą razem z nią, gdy przeniesiesz plik `.db` na inny komputer. Motyw **Ciemny/Jasny**
przełączysz w menu **Widok**.

### Co mówi kolumna „Obiekt"

Ta jedna kolumna niesie **pięć różnych odpowiedzi**, a każda ma inną receptę. Znacznik przed nazwą
mówi, skąd ta nazwa się wzięła - i czy jest tu dla Ciebie robota. To samo wyjaśnienie dostaniesz
po najechaniu myszą na komórkę.

| Co widzisz | Co to znaczy | Co z tym zrobić |
|---|---|---|
| **NGC7000** - zwykła nazwa | Obiekt rozpoznany. Nazwa jest w bazie na stałe | Nic. To jest stan docelowy |
| **↺ NGC7000** | Ta nazwa była przypisana, ale **Twoja ręka ją zdjęła**. Program pamięta, co zdjął | Jeśli to była pomyłka: **Obiekt ▾ → Przywróć cofnięte przypisanie**. Jeśli nie - zostaw, program sam jej nie przywróci |
| **? Mgławica Ameryka** | W pliku jest nazwa, której **program nie rozpoznał** - to jedyny stan, który JEST robotą | Albo **Obiekt ▾ → Przypisz obiekt…** (decyzja zostaje w bazie), albo **Popraw nagłówki…** (nazwa idzie do samego pliku, na zawsze) |
| **⟨NGC7000⟩** w nawiasach kątowych | To **propozycja z nazwy folderu**, nie fakt z pliku. Dotyczy gotowych obrazów, które nagłówka o obiekcie nie mają | Potwierdź ją gestem (**Obiekt ▾**), jeśli się zgadza. Do czasu potwierdzenia jest tylko podpowiedzią |
| **dark**, **flat** - nazwa bez znacznika, szarą kursywą | Klatka **kalibracyjna**: obiektu nie ma z definicji, bo nie fotografowała nieba | Nic. Tu nie ma czego poprawiać - dlatego program to wygasza |

Pusta komórka znaczy dokładnie tyle: plik nie mówi nic o obiekcie i program niczego nie zgaduje.

> Nagłówek grupy (przy **Grupuj wg: Obiekt**) mówi to samo co komórki pod nim - jest wygaszony
> tam, gdzie wygaszone są wiersze. Gdy grupa zbiera klatki w różnych stanach, nagłówek **milczy**,
> zamiast zgadywać stan większości.

**Szukanie po nazwie, jaką znasz.** Nad listą obiektów jest pole szukania. Wpisz cokolwiek —
`Ameryka Północna`, `NGC 7000`, `ngc7000` — trafi tak samo. Program zna nazwy potoczne, skróty
katalogowe i nie czepia się spacji, kropek ani wielkości liter.

**Zaznaczenie to Twój warsztat.** Cokolwiek zaznaczysz w tabeli, pasek pod spodem powie, ile tego
jest, i da akcje na tym zbiorze: **Obiekt ▾** (nazwij / cofnij), **Rodowód…** (z czego powstał
gotowy obraz albo czym skalibrowano klatkę), **Popraw nagłówki…**, **Uporządkuj nazwy plików…**
oraz **Wydaj na stół…**.

> Dwie ostatnie akcje **ruszają pliki na dysku** (zmieniają nazwy albo budują drzewo linków pod
> obróbkę w WBPP). Obie najpierw pokazują **podgląd** i nie robią nic, dopóki go nie zatwierdzisz.

---

## Krok 6 — Zaplanuj, co sfotografować

Poprzednie kroki opisują to, co **już masz**. **Planer** patrzy w przód: bierze Twoje stanowisko,
Twój sprzęt i dzisiejszą datę, i mówi, co da się dziś złapać — oraz ile materiału już na to zebrałeś.

Wejdź w **Planer**. Każdy wiersz to jeden cel:

| Kolumna | Co mówi |
|---|---|
| **Cel** / **Typ** | co to za obiekt (mgławica, galaktyka…) |
| **Rozmiar** / **Zestaw i kadr** | czy zmieści się w kadrze Twojego sprzętu |
| **Okno** / **Kulminacja** | kiedy dziś jest nad horyzontem i kiedy stoi najwyżej |
| **Pokrycie** | ile materiału już masz — **liczone z Twojego archiwum**, nie ze zgadywania |
| **Koszt B/D/W** | ile jeszcze trzeba, żeby domknąć |
| **Rada** | podpowiedź programu |
| **Plan** / **Notatka** | Twoja własna decyzja i Twój komentarz |

**Pokrycie liczy się z gotowych obrazów, nie z klatek na dysku.** Jeśli te same zdjęcia weszły do
dwóch stosów, program nie policzy ich dwa razy — pyta o godziny, które realnie siedzą w obrazie.

> Kolumna **Plan** jest **wyłącznie Twoja** — program nigdy sam nie oznaczy celu jako zrobionego.
> Podpowiada („✓ bez luk"), ale decyzję zapisuje tylko Twoja ręka.

---

## Przykład od początku do końca

Masz na dysku `D:\AstroFoto` z 4 000 plików FITS z dwóch sezonów, robionych dwoma teleskopami.

1. **Plik → Nowa baza…** → zakładasz `D:\AstroFoto\katalog.db`.
2. **Dostawa → Przyjmij nowe** → wskazujesz `D:\AstroFoto` → czekasz ~3 minuty. Podsumowanie:
   „pliki 4000 · nowe 4000 · rozpoznane obiekty 92%".
3. **Porządki** pokazuje **Porządki (3)**: Teleskopy bez etykiety — 2, Stanowiska bez nazwy — 1.
4. Nazywasz teleskopy `Newton 8"` i `Refraktor 80/480`, stanowisko `Taras`.
5. Zostaje **Klatki bez obiektu — 140**. Klikasz i widzisz trzy wiersze: `FlatWizard · 96`
   (nazwa z nagłówka, której program nie zna), **bez nazwy w nagłówku · 32** oraz
   **…z tego ze ścieżki · 3 nazwy · 32 klatki**.
   - `FlatWizard` to nie obiekt, tylko narzędzie — te klatki zostawiasz.
   - Klikasz **…z tego ze ścieżki → Zatwierdź ze ścieżki…**, przeglądasz trzy propozycje
     (`NGC6960`, `M31`, `IC1805`), odznaczasz jedną wątpliwą, zatwierdzasz resztę. Zostaje 12 klatek.
   - Te 12 nazywasz ręką: zaznaczasz, **Przypisz obiekt…**, wpisujesz `NGC 7000`.
6. **Zbiory → perspektywa Przegląd**, w panelu **Pola (kolumny)** dokładasz **Obiekt** i **Filtr** — widzisz
   cały dorobek ułożony po obiektach. Zapisujesz ten układ przez **★ Zapisz widok**.

Miesiąc później dogrywasz nową sesję do `D:\AstroFoto`. **Dostawa → Przyjmij nowe** (folder już
zapamiętany) → przechodzi w kilkanaście sekund, bo stare pliki są pomijane, dopisują się tylko nowe.

---

## Co robi się samo, a czego program nie zrobi

**Robi samo:**

- czyta nagłówki i buduje katalog (skan tylko odczytuje pliki),
- wyprowadza osie teleskopu, stanowiska i konfiguracji,
- rozpoznaje obiekty z katalogów, nazw potocznych, pozycji na niebie oraz filtry,
- wiąże gotowy obraz z klatkami, z których powstał,
- przy kolejnych dostawach pomija pliki, które już zna,
- pamięta ostatnią bazę i ostatni folder dostawy oraz wybrany motyw.

**Nie zrobi bez Twojej wyraźnej decyzji:**

- **nie zmienia, nie przenosi ani nie kasuje Twoich plików** podczas skanu,
- **nie wymyśla nazw** teleskopów i stanowisk — te nadajesz Ty,
- **nie zgaduje na siłę** obiektu, którego nie jest pewien — ląduje w kolejce przeglądu,
- **nie ufa folderowi bez pytania** — nazwa z katalogu jest propozycją, którą potwierdzasz,
- **nie oznacza celu jako zrobionego** w Planerze — to zapisuje wyłącznie Twoja ręka,
- **nie odwraca Twojego cofnięcia** — klatka, której zdjąłeś nazwę, nie dostanie jej z powrotem sama,
- operacje ruszające pliki na dysku (dopisanie karty `OBJECT`, zmiana nazw z faktów, budowa drzewa
  pod WBPP) to **osobne, jawne akcje** — zawsze najpierw pokazują podgląd, a zapis nagłówka ma kopię
  zapasową i **Cofnij**.

---

## Checklista pierwszego uruchomienia

- ☐ Program się otwiera (widać okno z paskiem **Dostawa / Zbiory / Porządki / Planer**)
- ☐ Założona baza — jej nazwa jest widoczna, cztery miejsca odblokowane
- ☐ **Przyjmij nowe** przeszło do końca, na dole jest podsumowanie
- ☐ W **Zbiory → Przegląd** widać klatki
- ☐ W **Porządki** nadane etykiety teleskopów i nazwy stanowisk (badge zgasł albo pokazuje tylko to, co zostawiasz)
- ☐ W **Porządki → Klatki bez obiektu** kolejka jest pusta **albo** wiesz, co w niej zostawiasz świadomie

---

## Ściąga — „chcę… → robię…"

| Chcę… | Robię… |
|---|---|
| Założyć katalog | **Plik → Nowa baza…** |
| Wrócić do swojego katalogu | **Plik → Otwórz bazę…** (albo sam wróci przy starcie) |
| Wczytać nowe zdjęcia | **Dostawa → Przyjmij nowe** |
| Wskazać inny folder niż zwykle | **Dostawa → Tryb zaawansowany → Wskaż katalog…** |
| Dodać gotowe obrazy po integracji | **Dostawa → Stosy → Wciągnij stosy…** |
| Nazwać teleskop | **Porządki → Teleskopy bez etykiety → dwuklik w Etykieta** |
| Nazwać miejsce | **Porządki → Stanowiska bez nazwy → dwuklik w Nazwa** |
| Nazwać klatki, których automat nie rozpoznał | **Porządki → Klatki bez obiektu → wiersz kolejki → Przypisz obiekt…** |
| Nazwać klatki, które właśnie widzę | **Zbiory → zaznacz → Obiekt ▾ → Przypisz obiekt…** |
| Nadać znowu tę samą nazwę, co przed chwilą | **Zbiory → zaznacz → Obiekt ▾ → → NAZWA** |
| Cofnąć własną pomyłkę w nazwie | **Zbiory → zaznacz → Obiekt ▾ → Cofnij przypisanie** |
| Przyjąć nazwy podpowiedziane przez foldery | **Porządki → Klatki bez obiektu → …z tego ze ścieżki → Zatwierdź ze ścieżki…** |
| Wpisać nazwę na stałe do pliku | **Porządki → Klatki bez obiektu → bez nazwy w nagłówku → Napraw nagłówek…** |
| Znaleźć obiekt po nazwie potocznej | **Zbiory → pole szukania nad listą obiektów** |
| Zobaczyć, z czego powstał gotowy obraz | **Zbiory → zaznacz obraz → Rodowód…** |
| Sprawdzić, co sfotografować dziś | **Planer** |
| Znaleźć duplikaty | **Porządki → Duplikaty** albo **Zbiory → perspektywa Duplikaty** |
| Zmienić motyw na jasny | **Widok → Jasny** |
| Sprawdzić, którą mam wersję | tytuł okna |

## FAQ

**Skan coś zmieni w moich plikach?** Nie. Skan tylko czyta nagłówki. Zmiany na dysku to osobne,
jawne akcje z podglądem.

**Zeskanowałem dwa razy ten sam folder — mam duplikaty?** Nie. Horreum rozpoznaje pliki po
zawartości i pomija znane. Duplikat powstaje tylko z realnie drugiej kopii pliku.

**Przeniosłem pliki na inny dysk i przeskanowałem — stracę historię?** Nie. Tożsamością jest
zawartość, nie ścieżka — Horreum rozpozna te same klatki pod nowym adresem.

**Nie widzę żadnych klatek.** Sprawdź, czy założyłeś i otworzyłeś bazę (nazwa widoczna) i czy
**Przyjmij nowe** dobiegło końca. W **Zbiory** upewnij się, że perspektywa to **Przegląd**, a filtry są puste.

**Część klatek nie ma obiektu.** To normalne dla nietypowych nazw w nagłówku — trafiają do kolejki
przeglądu w **Porządki → Klatki bez obiektu**, skąd nadasz im nazwę ręką.

**Nadałem złą nazwę — da się to odkręcić?** Tak. **Zbiory → zaznacz klatki → Obiekt ▾ → Cofnij
przypisanie**. Zdejmie nazwę, którą postawiła Twoja ręka albo folder; nazwa odczytana z pliku
zostaje, bo to nie jest Twoja pomyłka, tylko fakt z archiwum.

**Zdjąłem nazwę, a po „Rozwiąż" wróciła.** Nie wróci — cofnięcie jest trwałe do Twojej kolejnej
decyzji. Jeśli nazwa wróciła, to znaczy, że pochodzi **z nagłówka pliku**, a nie z ręki: żeby ją
zmienić na stałe, użyj **Napraw nagłówek…** i popraw sam plik.

**Nazwałem cały kubełek, a program mówi „przypisano 5 z 8".** Zdanie pod spodem wylicza, czemu
pominął resztę: kalibracja (nie ma obiektu z definicji), klatki z nazwą w nagłówku (ich się nie
nadpisuje bez potrzeby) albo klatki, które zmieniły się w międzyczasie.

**Czy „Napraw nagłówek…" zepsuje mi zdjęcie?** Nie — dopisuje wyłącznie opis (kartę `OBJECT`),
same dane obrazu zostają nietknięte. Przed zapisem widzisz listę plików i dokładną nazwę, a po
zapisie działa **Cofnij** (program trzyma kopię nagłówka).

**Skąd Planer wie, ile już mam?** Liczy godziny z Twojego archiwum — z gotowych obrazów i klatek,
które do nich weszły. Dlatego pokrycie rośnie dopiero wtedy, gdy materiał realnie przybywa.

<!-- APPENDIX-START: sekcja techniczna — usuwana z wersji PDF dla czytelnika -->

## Dla nas — mapowanie na system

> Ta sekcja jest dla utrzymujących projekt, nie dla użytkownika końcowego. Odcinana przy generowaniu PDF.

**Miejsca nawigacji (F5):** `Dostawa` = `PipelineView`, `Zbiory` = `FramesView`, `Porządki` =
`TasksView`, `Planer` = `PlannerView` (T1–T5). Osie (teleskop/obserwatorium/obiekt) to podstrony
Porządków.

**Cztery drogi nadania obiektu** (`horreum/gui/app.py` — `ObjectAxisView`; `horreum/gui/grid.py` —
`SelectionBar`): ręka z kolejki (`_on_assign` → `repo.user_assign_object`) · ręka ze Zbiorów
(`Obiekt ▾`, ten sam czasownik klingi) · potwierdzenie propozycji ścieżki (`_on_confirm_path` →
`resolver.path_proposals`, źródło `path`) · zapis karty `OBJECT` do PLIKU (`_on_repair` →
`RepairHeaderDialog` → `writeback`, jedyna droga tykająca dysk; gasi też nagrobek `user_cleared`).
Cofnięcie = `repo.clear_object_assignment`, zdejmuje wyłącznie `CLEARABLE_OBJECT_SOURCES`
(`path`, `user`); nagrobek przeżywa `run_resolver`.

**Kolejka przeglądu obiektów** (`gui/queries.review_queue`) ma cztery kubełki bezimiennych, każdy
rozszczepiony po źródle (połówka nietknięta + `· cofnięte ręką`): `object_review` (GROUP BY),
`nameless`, `nameless_raw`, `nameless_stacks`. Partycja musi domykać się do `review_frame_ids` —
walidator `_partycja` w `tests/test_gui_queries_object.py`.

**Etapy dostawy** = `scan_tree` → `run_grouper` → `run_resolver` → `run_calibration` →
`run_lineage` → `delta_report` (`horreum/gui/pipeline.py`). Ten sam łańcuch, w tej samej
kolejności, wykonuje fasada importu `import_fitsmirror.run_import` (P-G) — „po imporcie" i „po
Dostawie" znaczą od 2026-08-01 to samo. „Przyjmij nowe" = stage `all` na zapamiętanym `pipeline/last_source`
(QSettings). Skan przyrostowy: brama `(volume, path, mtime)`; ponowny skan pomija znane pliki;
tożsamość = `sha1_data`.

**Zadania Porządków** (`horreum/gui/tasks.py`, `_TASKS`) — dziesięć wierszy, każdy prowadzi na
powierzchnię (podstronę osi albo perspektywę Zbiorów), ale tylko część z nich jest ROBOTĄ:
`unresolved_lights` / `stacks_lineage_pending` / `telescopes_unlabeled` / `observatories_unnamed` /
`dup_frames` / `vanished_frames` / `retired_conflict_frames` — akcyjne (liczba pogrubiona, wchodzą
do odznaki sidebara); `superseded_frames` / `retired_frames` / `missing_copy_frames` — HISTORIA
(`_BEZ_ROBOTY`: wyszarzone i poza odznaką niezależnie od liczby, bo nic nie zginęło — dalej
klikalne).

**Perspektywy Zbiorów** (`horreum/gui/grid.py`, `PRESETS`): `Przegląd` / `Kalibracja` / `Duplikaty` /
`Zniknięte` / `Rodowód` / `Zastąpione` / `Wycofane` / `Brakujące kopie` / `Do przeglądu`, plus
zapisane przez użytkownika — te od migracji `0013` mieszkają w BAZIE (`saved_query`), nie
w QSettings, więc jadą razem z katalogiem na inną maszynę.

**Ścieżka ze źródła / CLI** (dla zaawansowanych, `horreum/cli.py`):

```
horreum init <baza.db>            # utwórz/zmigruj bazę (= Plik -> Nowa baza)
horreum scan <katalog> <baza.db>  # skan (--volume <serial>, --tier cold|scratch)
horreum group <baza.db>           # grupuj
horreum resolve <baza.db>         # rozwiąż
horreum delta <baza.db>           # podsumowanie (read-only)
horreum --version / --help
```

Operacje zaawansowane (osobne briefy, nie ta instrukcja): `horreum rename` (zmiana nazw plików z
faktów — DRY domyślnie, `--apply`/`--undo`), `horreum project` (drzewo linków/kopii pod WBPP — DRY
domyślnie, `--apply`). W GUI odpowiedniki żyją w Zbiorach („Wydaj na stół…", staging writebacku).

**Dystrybucja:** od 0.4.0 **onefile** — jeden `dist\horreum-gui.exe` z `packaging\build.ps1 -Onefile`,
publikowany jako `Horreum-<wersja>-windows-x64.exe`. Instalator NSIS i przenośny zip **wycofane**
(decyzja: „w jednym exe"); `packaging\horreum-installer.nsi` i wariant onedir zostają dla dev.
Numer wersji ma jednego właściciela (`pyproject.toml`), widać go w tytule okna — bramka
`tests/test_version.py`, sonda tytułu w buildzie.

**Status dokumentu:** trzon opisuje stan **0.6.0** (onefile zamiast zip+`_internal`, czwarte miejsce
nawigacji — Planer, cztery drogi nadania obiektu i cofnięcie, propozycje ze ścieżki, rodowód stosów,
szukanie po nazwach potocznych, perspektywy w bazie). Dopisane w wydaniu **0.9.0**: tabela
**„Co mówi kolumna »Obiekt«"** w Kroku 5 — pięć stanów kolumny z receptą do każdego.

> **Instrukcja jest o dwa wydania z tyłu.** Trzy rzeczy z **0.7.0**, których ten dokument nie
> opisuje krok po kroku: wiersz **„Obrazy bez rodowodu"** w Porządkach z perspektywą „Rodowód do
> potwierdzenia", **propozycja materiału** w panelu „Rodowód" (klatki nocy obrazu z wyborem innej
> nocy), **ręczne wskazanie zestawu** teleskop × kamera dla zdjęć z lustrzanki oraz **odniesienie
> czasu** dla stosów z aparatu. Z **0.8.0** dochodzą trzy drogi powrotu: **sierota kurateli**
> w Planerze (zdejmij albo przenieś oznaczenie, gdy katalog celów zmienił nazwę), **„Wycofaj"**
> dla klatki, której wszystkie kopie zniknęły z dysku, oraz wciąganie folderów **`STACKS`**
> zwykłym skanem. Z **0.9.0** — perspektywa **„Brakujące kopie"** (obraz stracił jedną z dwóch
> kopii). Gest **„Przywróć cofnięte przypisanie"** z 0.8.0 jest już opisany, w tabeli w Kroku 5.
> Pełny opis zmian → `CHANGELOG.md`.

**Nadal BEZ własnego opisu** (wskazane w instrukcji, ale nieopisane krok po kroku): **Wydaj na
stół…** (projekcje pod WBPP), **Uporządkuj nazwy plików…** (rename z faktów), **Popraw nagłówki…**
jako operacja masowa oraz panel **Rodowód…** w wariancie kalibracyjnym. Lead instrukcji mówi o nich
„mają dostać własny opis" — dopóki go nie ma, to jest dług, nie stan docelowy.

<!-- APPENDIX-END -->
