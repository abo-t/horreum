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

Python + PySide6 (GUI-first) + SQLite. Szczegóły instalacji i uruchomienia pojawią się wraz z pierwszym działającym plastrem.

## Licencja

MIT — zobacz [LICENSE](LICENSE).
