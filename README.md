# Horreum

Samodzielny menedżer biblioteki astrofotograficznej (suby i mastery) dla dowolnego drzewa plików.

> **Status:** wczesny rozwój. Schemat i API mogą się jeszcze zmieniać.

## Filozofia: baza = autorytet

Horreum odwraca klasyczny model „folder = prawda". Tutaj:

- **Baza danych jest autorytetem.** Pliki to zamrożony, append-only zimny magazyn. Foldery (np. drzewa wejściowe do WBPP) to jednorazowe projekcje generowane na żądanie z zapytania.
- **`sha1` = tożsamość pliku** — przeżywa zmianę nazwy i przeniesienie. Ścieżka to atrybut lokalizacji, nie tożsamość. Jeden plik (jedna zawartość) może mieć wiele lokalizacji.
- **Każda zmiana tożsamości to dopisanie zdarzenia** (append-only `event`), nigdy destrukcyjny update. Pełna historia i podróż w czasie z pudełka.
- **Jedyne drzwi do zapisu** — pojedyncza warstwa repozytorium emitująca zdarzenia, pilnowana meta-testem. Relacje (kalibracja, lineage masterów) są jawne, nie wyprowadzane z parsowania nazw plików.

## Wbudowany resolver tożsamości

Horreum rozpoznaje obiekty niezależnie od zapisu w nagłówku: katalogi krzyżowe (Messier / Caldwell → NGC / IC, polityka NGC-wins), nazwy potoczne oraz fakt sprzętowy kamery (np. warianty ZWO ASI2600). Działa na czystym drzewie każdego użytkownika, bez zależności od żadnego zewnętrznego narzędzia.

## Stos technologiczny

Python 3.9+ · PySide6 (GUI desktop) · SQLite · astropy (czytnik nagłówków FITS). Rdzeń bazy jest
bez zależności zewnętrznych (stdlib); astropy wchodzi dopiero na etapie skanu.

## Instalacja i uruchomienie

### Wersja zamrożona (Windows, bez Pythona)

Pobierz archiwum z [Releases](../../releases), rozpakuj i uruchom:

- `horreum-gui.exe` — aplikacja okienkowa (główny sposób pracy),
- `horreum.exe` — to samo z linii poleceń (uruchamiaj z terminala: `horreum.exe --help`).

Oba pliki dzielą folder `_internal/` — trzymaj je razem. Baza to plik `.db`, który wybierasz
w aplikacji; nie jest przywiązana do katalogu programu.

### Ze źródła (dowolny system)

```bash
pip install -e ".[gui]"
python -m horreum.gui        # aplikacja okienkowa
horreum --help               # linia poleceń
```

## Szybki start

1. **Nowa baza** — wskaż plik `.db` (pusty powstanie z migracjami).
2. **Skanuj** drzewo z plikami FITS/XISF — baza wciąga nagłówki (append-only, `sha1` = tożsamość).
3. **Grupuj** — Horreum wyprowadza osie teleskopu i konfiguracji.
4. **Rozwiąż** — resolver rozpoznaje obiekty (katalogi krzyżowe, nazwy potoczne, ciała Układu).
5. **Przegląd** — co wymaga ręcznej decyzji, trafia na listę; resztą zarządzasz z siatki.

## Budowanie wersji zamrożonej

Wymaga Windows + Pythona. Build idzie z czystego, izolowanego środowiska (`.venv-build`) —
skrypt tworzy je sam:

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

Wynik: `dist\horreum\` (spakuj cały folder do dystrybucji). Szczegóły decyzji pakietowania —
`packaging\horreum.spec`.

## Licencja

MIT — zobacz [LICENSE](LICENSE).
