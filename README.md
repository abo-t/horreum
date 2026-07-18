# Horreum

**English** · [Polski](#horreum-po-polsku)

Standalone catalog manager for a deep‑sky astrophotography library (light frames and masters),
working over any file tree.

![Horreum main window — the Collections view: a faceted, queryable catalog over a FITS/XISF archive](doc/horreum-gui.png)

*The Collections view — faceted axes (object, filter, kind, telescope, night) over the whole archive, dark theme.*

Horreum inverts the classic *"folder = truth"* model: a **SQLite database is the authority**, and a
file's **`sha1` content hash is its identity** — surviving renames and moves. Every identity change is
an appended event, never a destructive update, so you get full history and time‑travel out of the box.
Scanning only **reads** your files — it never moves, renames, or deletes them.

Horreum derives the axes you actually search by — **telescope**, **observing site** (from GPS in the
header), and **object** (Messier / Caldwell → NGC / IC cross‑catalogs, common names, Solar‑System
bodies) — straight from FITS/XISF headers, independent of how your folders are arranged.

**Who it's for:** astrophotographers who want one queryable catalog over a large FITS/XISF archive.

**Status:** early development — schema and API may still change. The desktop UI and documentation are
currently **Polish**; UI internationalization is planned. The full guide is in the Polish sections below.

**Contributing:** a hobby project maintained in spare time — issues and pull requests are welcome, but
responses may take a while (that's expected, not neglect). See [CONTRIBUTING.md](CONTRIBUTING.md) and
[CHANGELOG.md](CHANGELOG.md).

---

## Horreum (po polsku)

Samodzielny menedżer biblioteki astrofotograficznej (suby i mastery) dla dowolnego drzewa plików.

![Horreum — główne okno, widok Zbiory: przeszukiwalny katalog z facetami nad archiwum FITS/XISF](doc/horreum-gui.png)

*Widok „Zbiory" — osie-facety (obiekt, filtr, rodzaj, teleskop, noc) nad całym archiwum; motyw ciemny.*

> **Status:** wczesny rozwój. Schemat i API mogą się jeszcze zmieniać.
>
> **Nowy użytkownik?** Instrukcja krok po kroku (zakładanie bazy, pierwsza konfiguracja, obsługa):
> [doc/instrukcja.md](doc/instrukcja.md).

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
