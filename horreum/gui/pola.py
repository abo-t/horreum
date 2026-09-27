"""Pokrycie POL (kolumn-keywordów) policzone tak, żeby wątek GUI na nie nie czekał - Qt-wolny rdzeń
workera `grid.PolaWorker`.

`queries.keyword_facets` to `COUNT(DISTINCT frame_id)` per keyword po CAŁEJ tabeli `cards`: zmierzone
5,6-5,9 s na kopii żywej bazy (16 901 klatek, ~1 mln wierszy) i 3,4-3,8 s na bazie syntetycznej
tej samej wielkości - a panel „Pola" przeładowywał je po KAŻDYM przebiegu Dostawy, także takim,
który nie ruszył ani jednej karty. Stąd dwie rzeczy w jednym przebiegu: liczymy poza wątkiem GUI
(worker otwiera własne połączenie) i nie liczymy wcale, gdy karty się nie zmieniły.

ODCISK KART = `(max(rowid), count(*), total(length(keyword)))`. Zmierzone na bazie syntetycznej
(1 014 408 wierszy): 124-141 ms, jedno przejście po indeksie pokrywającym `idx_cards_kw_num`
(`max(rowid)` sam 0,1 ms, z `count(*)` 70-88 ms). Każdy człon łapie inną drogę zmiany:
  * `max(rowid)` rośnie przy KAŻDYM wstawieniu - tabela nie ma AUTOINCREMENT, ale nowe wiersze
    dostają `max+1`, więc wymiana zeznania klatki (`DELETE` + `INSERT`) podnosi go, o ile wymieniana
    klatka nie trzyma samego szczytu;
  * `count(*)` łapie samo kasowanie i wymianę zeznania na krótsze albo dłuższe;
  * `total(length(keyword))` łapie wymianę zeznania OSTATNIEJ klatki (szczyt rowid wraca na to samo
    miejsce) na tyle samo kart o innych keywordach.
Ślepa plama zostaje jedna: wymiana zeznania klatki ze szczytu rowid na tyle samo kart, których
keywordy mają łącznie tę samą długość. Koszt pomyłki to pokrycie pól sprzed tej wymiany do
najbliższej zmiany kart - nie zapis ani nie zbiór klatek.

`PRAGMA data_version` NIE WYSTARCZA: mówi „ktoś inny zapisał coś w bazie", nie „zmieniły się
karty". Każdy przebieg Dostawy pisze zdarzenia, więc licznik rośnie zawsze i nie oszczędziłby ani
jednego przeliczenia; a zapisu przez WŁASNE połączenie (gesty gridu przez `self.con`) nie widzi
wcale, więc w tej drodze pomyliłby się w drugą stronę.

Odcisk i pokrycie liczone są w JEDNEJ transakcji czytającej (WAL daje jej migawkę), więc odcisk
zwrócony z wynikiem opisuje dokładnie dane, z których ten wynik powstał - zapis, który wpadnie
w trakcie liczenia, zmieni odcisk następnego przebiegu i wymusi przeliczenie."""

from horreum.gui import queries


def odcisk_kart(con):
    """Tani odcisk tabeli `cards` - patrz docstring modułu. Krotka porównywalna `==`."""
    r = con.execute(
        "SELECT max(rowid), count(*), total(length(keyword)) FROM cards").fetchone()
    return (r[0], r[1], r[2])


def pokrycie(con):
    """Pokrycie pól jako lista `{"keyword", "n"}` - to samo co `queries.keyword_facets`, tylko
    słownikami, nie `sqlite3.Row`: wynik przechodzi między wątkami i nie ma prawa zależeć od
    połączenia, które go wydało. Moduł `queries` czytany W CHWILI WYWOŁANIA (nie `from … import`),
    więc podmiana w teście trafia i tutaj."""
    return [{"keyword": r["keyword"], "n": r["n"]} for r in queries.keyword_facets(con)]
