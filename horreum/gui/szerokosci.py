"""Szerokości kolumn listy z treści - rachunek bez Qt, wspólny dla planera i Znajdź (AR-175, AR-346).

`ResizeToContents` i `resizeColumnToContents` liczą szerokość przejściem Qt po komórkach, a każda komórka to
osiem pythonowych wywołań `data()` modelu: siedem ról opcji stylu (`QStyledItemDelegate::initStyleOption`
przez `multiData`, model jej nie nadpisuje) i `SizeHintRole` (`QStyledItemDelegate::sizeHint`). Zmierzone
natywnie na kopii pf4: pierwsze wejście w Znajdź to 40 000 wywołań (pięć kolumn × 1000 wierszy × 8 ról)
i klik w kafel Domu 455-795 ms. Tu szerokość tekstu komórki liczy wołający metryką fontu, a moduł składa
regułę Qt (najszerszy tekst + margines komórki, nie mniej niż podpowiedź nagłówka) i wie, KTÓRE wiersze
bierze Qt (`wiersze_podpowiedzi`) - więc wynik jest tą samą liczbą, którą dałby Qt dla tych samych wierszy.

Metrykę podaje wołający (widżet zna czcionkę, styl i model), więc rachunek sprawdza się bez okna."""


def wiersze_podpowiedzi(gora, dol, liczba, precyzja):
    """Numery wierszy, z których Qt liczy podpowiedź szerokości kolumny, w jego kolejności - wierne
    `QTableView::sizeHintForColumn` (qtableview.cpp:2519-2590, Qt 6.9.2) dla widoku, w którym wiersz widoku
    jest wierszem modelu (bez wierszy ukrytych i przestawionych - pilnuje wołający):

      * najpierw kadr `gora..dol` włącznie, najwyżej `precyzja` wierszy;
      * potem na przemian powyżej i poniżej kadru (nieparzysta liczba przetworzonych - w górę, o ile jest
        dokąd; koniec modelu - też w górę), aż `precyzja` wierszy albo cały model.

    `gora` = `max(0, verticalHeader.visualIndexAt(0))`; `dol` = `visualIndexAt(wysokość kadru)` albo -1, gdy
    tabela jest niewidoczna albo krótsza niż kadr - Qt bierze wtedy ostatni wiersz modelu. `precyzja` =
    `QHeaderView.resizeContentsPrecision()`: 0 - sam kadr, -1 - wszystkie wiersze, domyślnie 1000. Wiersze
    ukryte Qt pomija - tu ich nie ma z założenia wołającego."""
    if dol == -1:
        dol = liczba - 1
    out = []
    przetworzone = 0
    r = gora
    while r <= dol:
        out.append(r)
        przetworzone += 1
        if przetworzone == precyzja:
            break
        r += 1
    ostatni = liczba - 1
    gorny, dolny = gora, r - 1
    if precyzja == 0 or ostatni < gorny:
        return out
    while przetworzone != precyzja and (gorny > 0 or dolny < ostatni):
        if (przetworzone % 2 and gorny > 0) or dolny == ostatni:
            gorny -= 1
            out.append(gorny)
        else:
            dolny += 1
            out.append(dolny)
        przetworzone += 1
    return out


def szerokosci_kolumn(szerokosc_tresci, wiersze, kolumny, margines, podpowiedzi):
    """Szerokość każdej kolumny z `kolumny` = najszerszy tekst jej komórek w `wiersze` plus `margines`, nie mniej
    niż `podpowiedzi[c]` (podpowiedź sekcji nagłówka) - ta sama liczba, którą daje `ResizeToContents`
    (`max(sizeHintForColumn, sectionSizeHint)`) dla TYCH SAMYCH wierszy.

    `szerokosc_tresci(wiersz, kolumna)` - szerokość samego tekstu komórki w px (sufit), BEZ marginesu komórki
    i bez linii siatki (te niesie `margines`); `None` - komórka bez tekstu, nie liczy się. Wartość ujemna jest
    dozwolona (podpis belki grupy pomniejszony o kolumny spanu - wołający w `grid.py`). Pusta lista wierszy -
    podpowiedzi nagłówka.

    Wiersze wybiera wołający: planer podaje wszystkie (szerokość nie schodzi poniżej treści, więc elizji nie
    ma - `planner.py`, `_COLUMNS`; przy > 1000 wierszach bywa szerszy niż Qt), Znajdź - wiersze Qt
    (`wiersze_podpowiedzi`), bo ma dawać dokładnie szerokości `resizeColumnToContents`."""
    out = []
    for c, kolumna in enumerate(kolumny):
        tekst = max((s for s in (szerokosc_tresci(w, kolumna) for w in wiersze) if s is not None), default=0)
        out.append(max(tekst + margines, podpowiedzi[c]))
    return out
