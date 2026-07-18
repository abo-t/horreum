# Horreum — instrukcja obsługi

*Dla osoby, która pobrała Horreum z GitHuba i chce zapanować nad własnym archiwum astrofoto —
bez znajomości programowania. Przeprowadzi Cię od pustej bazy, przez pierwsze wczytanie zdjęć,
po nazwanie sprzętu i przeglądanie zbiorów. Zaawansowane operacje (zmiana nazw plików na dysku,
budowa drzewa pod WBPP) mają własne, osobne opisy — tutaj budujemy fundament.*

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
    4. Uporządkuj               (Porzadki -> nazwij teleskopy i stanowiska)
    5. Przeglądaj               (Zbiory -> perspektywy)

---

## Wersja gotowa (`.exe`) czy ze źródła?

**Jedno pytanie:** czy masz Windows i chcesz po prostu kliknąć, żeby ruszyło?

| | Kiedy tak | Co robisz |
|---|---|---|
| **Wersja gotowa** (zalecana) | Masz Windows, nie chcesz nic instalować | Pobierasz gotowy folder z **Releases**, rozpakowujesz, klikasz `horreum-gui.exe` |
| **Ze źródła** | Masz Linux/Mac, albo chcesz najnowszy kod / własne zmiany | Instalujesz Pythona i uruchamiasz komendą |

Koszt pomyłki jest zerowy — obie wersje działają na tej samej bazie. Jeśli wahasz się, wybierz
**wersję gotową**. Opis obu jest w Kroku 1.

---

## Mapa ekranu

Po uruchomieniu widzisz jedno okno. Z lewej pasek z **trzema miejscami**, reszta to bieżący widok:

    Menu:  Plik            Widok
           |                |
           Otworz/Nowa      Ciemny/Jasny
           baza

    +-----------+------------------------------------------+
    | Dostawa   |   <- Krok 3: wczytujesz tu nowe zdjęcia   |
    | Zbiory    |   <- Krok 5: przegladasz katalog          |
    | Porzadki  |   <- Krok 4: nazywasz sprzet, przeglad    |
    +-----------+------------------------------------------+

- **Dostawa** — tu wpuszczasz nowe zdjęcia do katalogu.
- **Zbiory** — biblioteka wszystkich klatek; filtrujesz i układasz „perspektywami".
- **Porządki** — lista rzeczy do zrobienia (nienazwany sprzęt, klatki bez obiektu) i osie
  Teleskop / Stanowisko / Obiekt. Cyfra przy nazwie, np. **Porządki (3)**, mówi, ile zadań czeka.

---

## Krok 1 — Uruchom program

### Wersja gotowa (Windows)

1. Wejdź na stronę projektu na GitHubie, w zakładkę **Releases**.
2. Pobierz archiwum `.zip`, **rozpakuj cały folder** (np. na pulpit).
3. Wejdź do rozpakowanego folderu i uruchom **`horreum-gui.exe`** (dwuklik).

> Trzymaj plik `horreum-gui.exe` razem z folderem `_internal`, który leży obok — to jego „silnik".
> Nie przenoś samego `.exe` w inne miejsce. Windows przy pierwszym uruchomieniu może ostrzec, że
> to nieznana aplikacja — to normalne dla programów spoza sklepu; wybierz „Więcej informacji →
> Uruchom mimo to".

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
Od tej chwili nazwa bazy jest widoczna, a trzy miejsca w pasku bocznym się odblokowują.

> Bazę zakładasz **pustą** — to normalne, że po tym kroku nic w niej nie ma. Zdjęcia wpuścisz w Kroku 3.
> Gdy następnym razem otworzysz program, sam wróci do ostatnio używanej bazy — nie musisz jej szukać.
> Chcesz później wrócić do tej bazy ręcznie? **Plik → Otwórz bazę…**

---

## Krok 3 — Przyjmij pierwszą dostawę

To jest pierwsza konfiguracja: pokazujesz Horreum, gdzie leżą Twoje zdjęcia, a on buduje z nich katalog.

1. Wejdź w miejsce **Dostawa** (pasek boczny).
2. Kliknij dużą złotą akcję **Przyjmij nowe (skan → grupuj → rozwiąż → delta)**.
3. Przy **pierwszym** uruchomieniu program zapyta o folder — wskaż **główny katalog z astrofoto**
   (może zawierać dowolnie zagnieżdżone podfoldery; Horreum zejdzie w głąb sam).
4. Poczekaj. Pasek postępu i licznik pokazują, ile plików już przeszło. Duże archiwa idą minutami —
   to jednorazowy koszt.

**Co oznaczają cztery etapy** (Horreum robi je po kolei, jednym kliknięciem):

| Etap | Co się dzieje |
|---|---|
| **skan** | czyta nagłówki plików i wpisuje klatki do katalogu (nic nie zmienia na dysku) |
| **grupuj** | wyprowadza osie teleskopu i konfiguracji sprzętu |
| **rozwiąż** | rozpoznaje obiekty (NGC/Messier/…), stanowiska (GPS) i filtry |
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

### Przejrzyj obiekty

**Klatki bez obiektu ›** otwiera **Przegląd obiektów** — bibliotekę rozpoznanych obiektów oraz
**Kolejkę przeglądu** z klatkami, które czekają na rozstrzygnięcie. W tej wersji to **podgląd**:
widzisz, co zostało, ale ręczne przypisywanie obiektu dojdzie w kolejnej odsłonie. Filtry u góry
(**Teleskop**, **Filtr**) zawężają, co widać.

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

Panel **Pola** z lewej pozwala dołożyć kolumny (Obiekt, Filtr, Kamera…). Własne ułożenie filtrów
zapiszesz jako nową perspektywę. Motyw **Ciemny/Jasny** przełączysz w menu **Widok**.

---

## Przykład od początku do końca

Masz na dysku `D:\AstroFoto` z 4 000 plików FITS z dwóch sezonów, robionych dwoma teleskopami.

1. **Plik → Nowa baza…** → zakładasz `D:\AstroFoto\katalog.db`.
2. **Dostawa → Przyjmij nowe** → wskazujesz `D:\AstroFoto` → czekasz ~3 minuty. Podsumowanie:
   „pliki 4000 · nowe 4000 · rozpoznane obiekty 92%".
3. **Porządki** pokazuje **Porządki (3)**: Teleskopy bez etykiety — 2, Stanowiska bez nazwy — 1.
4. Nazywasz teleskopy `Newton 8"` i `Refraktor 80/480`, stanowisko `Taras`. Badge gaśnie.
5. **Zbiory → perspektywa Przegląd**, w panelu **Pola** dokładasz **Obiekt** i **Filtr** — widzisz
   cały dorobek ułożony po obiektach.

Miesiąc później dogrywasz nową sesję do `D:\AstroFoto`. **Dostawa → Przyjmij nowe** (folder już
zapamiętany) → przechodzi w kilkanaście sekund, bo stare pliki są pomijane, dopisują się tylko nowe.

---

## Co robi się samo, a czego program nie zrobi

**Robi samo:**

- czyta nagłówki i buduje katalog (skan tylko odczytuje pliki),
- wyprowadza osie teleskopu, stanowiska i konfiguracji,
- rozpoznaje obiekty z katalogów i nazw potocznych oraz filtry,
- przy kolejnych dostawach pomija pliki, które już zna,
- pamięta ostatnią bazę i ostatni folder dostawy oraz wybrany motyw.

**Nie zrobi bez Twojej wyraźnej decyzji:**

- **nie zmienia, nie przenosi ani nie kasuje Twoich plików** podczas skanu,
- **nie wymyśla nazw** teleskopów i stanowisk — te nadajesz Ty,
- **nie zgaduje na siłę** obiektu, którego nie jest pewien — ląduje w kolejce przeglądu,
- zaawansowane operacje ruszające pliki na dysku (zmiana nazw z faktów, budowa drzewa pod WBPP)
  to **osobne, jawne akcje** — mają własne opisy i zawsze najpierw pokazują podgląd.

---

## Checklista pierwszego uruchomienia

- ☐ Program się otwiera (widać okno z paskiem **Dostawa / Zbiory / Porządki**)
- ☐ Założona baza — jej nazwa jest widoczna, trzy miejsca odblokowane
- ☐ **Przyjmij nowe** przeszło do końca, na dole jest podsumowanie
- ☐ W **Zbiory → Przegląd** widać klatki
- ☐ W **Porządki** nadane etykiety teleskopów i nazwy stanowisk (badge zgasł albo pokazuje tylko to, co zostawiasz)

---

## Ściąga — „chcę… → robię…"

| Chcę… | Robię… |
|---|---|
| Założyć katalog | **Plik → Nowa baza…** |
| Wrócić do swojego katalogu | **Plik → Otwórz bazę…** (albo sam wróci przy starcie) |
| Wczytać nowe zdjęcia | **Dostawa → Przyjmij nowe** |
| Wskazać inny folder niż zwykle | **Dostawa → Tryb zaawansowany → Wskaż katalog…** |
| Nazwać teleskop | **Porządki → Teleskopy bez etykiety → dwuklik w Etykieta** |
| Nazwać miejsce | **Porządki → Stanowiska bez nazwy → dwuklik w Nazwa** |
| Znaleźć duplikaty | **Porządki → Duplikaty** albo **Zbiory → perspektywa Duplikaty** |
| Zmienić motyw na jasny | **Widok → Jasny** |

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
przeglądu w **Porządki → Klatki bez obiektu**.

<!-- APPENDIX-START: sekcja techniczna — usuwana z wersji PDF dla czytelnika -->

## Dla nas — mapowanie na system

> Ta sekcja jest dla utrzymujących projekt, nie dla użytkownika końcowego. Odcinana przy generowaniu PDF.

**Miejsca nawigacji (F5):** `Dostawa` = `PipelineView`, `Zbiory` = `FramesView`, `Porządki` =
`TasksView`. Osie (teleskop/obserwatorium/obiekt) to podstrony Porządków.

**Etapy dostawy** = `scan_tree` → `run_grouper` → `run_resolver` → `delta_report`
(`horreum/gui/pipeline.py`). „Przyjmij nowe" = stage `all` na zapamiętanym `pipeline/last_source`
(QSettings). Skan przyrostowy: brama `(volume, path, mtime)`; ponowny skan pomija znane pliki;
tożsamość = `sha1_data`.

**Zadania Porządków** (`horreum/gui/tasks.py`, `_TASKS`): `unresolved_lights` / `telescopes_unlabeled`
/ `observatories_unnamed` / `dup_frames` (perspektywa `Duplikaty`, flaga `only_dups`) — akcyjne;
`xisf_frames` / `vanished_frames` — informacyjne (wyszarzone).

**Perspektywy Zbiorów** (`horreum/gui/grid.py`, `PRESETS`): `Przegląd` / `Kalibracja` / `Duplikaty` /
`Do przeglądu` + zapisane w QSettings.

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

**Status dokumentu:** opisuje stan po F1–F7 (pień scalenia kompletny, oś obserwatorium jako podstrona
Porządków, portfel naświetleń F7). Mapa stanowisk (F8) i ręczne przypisywanie obiektu (import-legacy)
— w przygotowaniu; gdy wejdą, dopisać sekcje w Kroku 4/5.

<!-- APPENDIX-END -->
