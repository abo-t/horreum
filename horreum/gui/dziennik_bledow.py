"""Dziennik błędów programu (AR-312) - plik, do którego straż błędu programu (`app.StrazBledowProgramu`)
dopisuje każde zgłoszenie: czas, wersję, wątek, `Typ: opis @ plik:N` i pełny ślad. Wydanie okienkowe
nie ma `stderr` (`console=False`), więc poza oknem błędu nie zostawało nic - człowiek, który okno
zamknął, nie miał czego pokazać ani do czego wrócić. Plik zostaje lokalnie, nic nie jest wysyłane.

PIĄTE DRZWI ZAPISU (bramka `tests/test_writeback_safety.py`, `DOORS`): moduł mutuje WYŁĄCZNIE plik
programu pod katalogiem dziennika podanym przez wołającego - nigdy plik archiwum - i wyłącznie w trzech
funkcjach modułu: `_utworz_katalog` (`os.makedirs`), `_obroc` (`os.replace` w obrębie katalogu)
i `_dopisz` (`open` w trybie dopisku). Bramka przypina tę mapę; nowe miejsce mutacji ją przewraca.

Qt-wolny (test izolacji `test_gui_isolation.py`): katalog wylicza straż (`QStandardPaths`), tu jest sam
zapis. Dopisek krótki - otwórz, dopisz, zamknij - więc druga instancja programu pisze do tego samego
pliku bez trzymanego uchwytu; obrót, który trafi na cudzy uchwyt (`WinError 32`), nie zatrzymuje dopisku
(wpis niesie wiersz o nieudanym obrocie).

ROTACJA: `PROG_BAJTOW` = 1 MiB, `ZAPASOWE` = 2 (`bledy.log`, `.1`, `.2`; najstarszy wypada). Wpis ma
0,5-1,5 KB (zmierzone 2026-10-22 na śladach z kodu pakietu), więc plik mieści ~700-2000 zgłoszeń, a trzy
pliki ≤ 3 MiB - kilka tysięcy; 1 MiB otwiera Notatnik od ręki i mieści się w każdym załączniku.

POWTÓRZENIE: zgłoszenie z nagłówkiem i śladem identycznym jak poprzedni pełny wpis tego procesu idzie
krótkim wierszem z licznikiem (bezstratnie - treść stoi wpis wyżej). Seria z `paintEvent` (3 zgłoszenia
w 50 ms, zmierzone w fali 25) pełnymi wpisami wypychałaby całą historię w kilkadziesiąt sekund."""
import os
import threading

NAZWA = "bledy.log"
PROG_BAJTOW = 1024 * 1024
ZAPASOWE = 2

# Hak straży bywa wołany z dowolnego wątku (`threading.excepthook`, slot obiektu w `QThread`).
_ZAMEK = threading.Lock()


def sciezka(katalog):
    """Ścieżka pliku dziennika w katalogu dziennika."""
    return os.path.join(katalog, NAZWA)


class Dziennik:
    """Dziennik w katalogu `katalog` (bezwzględnym - inaczej zapis trafiłby do katalogu bieżącego,
    który w wydaniu bywa czymkolwiek: błąd programu, nie stan)."""

    def __init__(self, katalog):
        if not os.path.isabs(katalog):
            raise ValueError(f"katalog dziennika błędów musi być bezwzględny: {katalog!r}")
        self.katalog = os.path.normpath(katalog)
        self.sciezka = sciezka(self.katalog)
        self._ostatni = None        # (nagłówek, ślad) ostatniego PEŁNEGO wpisu tego procesu
        self._powtorzenia = 0

    def zapisz(self, *, czas, wersja, watek, naglowek, slad):
        """Dopisz zgłoszenie; zwraca ścieżkę pliku. Porażka założenia katalogu albo dopisku wychodzi
        wyjątkiem do wołającego (straż mówi o niej w oknie) - porażka obrotu nie: dopisek idzie dalej
        z wierszem o niej."""
        with _ZAMEK:
            glowa = f"==== {czas} | Horreum {wersja} | pid {os.getpid()} | {watek}"
            # Stan serii zmienia dopiero UDANY dopisek (koniec funkcji): po porażce w pliku nie ma
            # wiersza, więc następny nie może dostać numeru o jeden za wysokiego.
            powtorzenia = self._powtorzenia + 1 if (naglowek, slad) == self._ostatni else 0
            if powtorzenia:
                wpis = f"{glowa} | powtórzenie {powtorzenia}: {naglowek}\n"
            else:
                wpis = f"{glowa}\n{naglowek}\n{slad.rstrip()}\n\n"
            _utworz_katalog(self.katalog)
            try:
                rozmiar = os.path.getsize(self.sciezka)
            except FileNotFoundError:
                rozmiar = 0
            if rozmiar and rozmiar + len(wpis.encode("utf-8", "backslashreplace")) > PROG_BAJTOW:
                try:
                    _obroc(self.sciezka)
                except OSError as exc:
                    wpis = f"(obrót dziennika nie powiódł się: {type(exc).__name__}: {exc})\n" + wpis
            _dopisz(self.sciezka, wpis)
            self._ostatni, self._powtorzenia = (naglowek, slad), powtorzenia
            return self.sciezka


def _utworz_katalog(katalog):
    os.makedirs(katalog, exist_ok=True)


def _obroc(sciezka_pliku):
    """`.1` → `.2` … aż do `ZAPASOWE` (najstarszy nadpisany - wypada), potem plik → `.1`."""
    for i in range(ZAPASOWE - 1, 0, -1):
        if os.path.exists(f"{sciezka_pliku}.{i}"):
            os.replace(f"{sciezka_pliku}.{i}", f"{sciezka_pliku}.{i + 1}")
    os.replace(sciezka_pliku, f"{sciezka_pliku}.1")


def _dopisz(sciezka_pliku, tekst):
    with open(sciezka_pliku, "a", encoding="utf-8", errors="backslashreplace") as fh:
        fh.write(tekst)
