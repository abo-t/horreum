"""Wskaźnik zajętości z NAZWANĄ FAZĄ — jeden dla wszystkich powierzchni okna (F-1).

Żądanie Zdzinia z firsthandu 2026-08-04, dosłowne: „musi być jakieś wskazanie, że aplikacja coś
robi, a nie się powiesiła — najlepiej z opisem: czytam bazę / czytam nagłówki". Faza jest więc
CZASOWNIKIEM w pierwszej osobie, a nie rzeczownikiem stanu: „Czytam bazę…", nie „Ładowanie".

DLACZEGO TO NIE JEST WĄTEK. Operacje, które ten moduł opisuje, KOŃCZĄ SIĘ ustawieniem widżetów
(tabela, kolejka, biblioteka), a widżety wolno tknąć wyłącznie z wątku GUI — przeniesienie ich
w tło nie skróciłoby zamrożenia, tylko przesunęło je do slotu. Etapy, które realnie liczą w tle,
mają już swój wątek i swój pasek (`PipelineWorker` + `PipelineView`); ten moduł ich NIE dotyczy
i nie jest ich zamiennikiem.

ZMIERZONE PRZED NAPISANIEM (żywa kopia `pf4`, 16 648 klatek, widżety POKAZANE — bez `show()`
pomiar broni zepsutego kodu, lekcja z tego samego firsthandu):

    start aplikacji (otwarcie bazy + montaż 4 widoków)   4 649 ms   ← okna NIE MA na ekranie
    grid `refresh()`                                     1 000 ms
    odświeżenie widoków po etapie Dostawy                ~1 200 ms
    `run_resolver` („Rozwiąż")                              924 ms   ← ma już pasek Dostawy

Pierwszy wiersz jest najgorszy z możliwych: przez te sekundy nie ma NICZEGO na ekranie, więc
„czy ono w ogóle wstało" jest pytaniem bez powierzchni, na której mogłaby stanąć odpowiedź.

To JEDEN z plików warstwy widżetów, którym wolno importować PySide6 (`tests/test_gui_isolation.py`
wymienia je z imienia). Rdzeń i read-model zostają bez Qt.
"""
from contextlib import contextmanager

from PySide6.QtCore import QEventLoop, Qt
from PySide6.QtWidgets import QApplication


class Phase:
    """Uchwyt fazy w biegu — pozwala DOPOWIEDZIEĆ, co się właśnie dzieje.

    Operacja policzalna ma mówić licznikiem („Zapisuję: 12 z 34"), a nie jednym zdaniem na całość:
    zdanie bez liczby odróżnia „trwa" od „zawiesiło się" tylko przez pierwsze kilka sekund, licznik
    — zawsze. Operacja niepoliczalna zostaje przy samym czasowniku i to jest uczciwe."""

    def __init__(self, say):
        self._say = say

    def say(self, text):
        self._say(text)
        repaint()


def repaint():
    """Wymuś przemalowanie, ZANIM ruszy praca — inaczej opis fazy nie zdąży pojawić się na ekranie
    i cały wskaźnik jest bezużyteczny (Qt maluje w pętli zdarzeń, do której długa operacja nie
    wraca aż do końca).

    `ExcludeUserInputEvents` jest tu warunkiem bezpieczeństwa, nie optymalizacją: bez niego
    `processEvents` doręczyłby kliknięcia zebrane w kolejce i user mógłby wejść w drugą akcję
    ZE ŚRODKA pierwszej — reentrancja w miejscu, które właśnie przebudowuje model tabeli."""
    app = QApplication.instance()
    if app is not None:
        app.processEvents(QEventLoop.ExcludeUserInputEvents)


@contextmanager
def busy(say, text):
    """Otocz długą operację na wątku GUI: nazwij fazę, pokaż ją, postaw kursor oczekiwania.

    `say` = dokąd idzie opis (etykieta fazy okna, pasek statusu widoku, etykieta okna dialogowego).
    Wybór należy do wołającego, bo tylko on wie, co user w tej chwili WIDZI: przy starcie nie ma
    jeszcze zamontowanych widoków, więc faza musi trafić na środek okna.

    FAZA NIE SPRZĄTA PO SOBIE SAMA — ostatnie słowo należy do wołającego. Wymuszone czyszczenie
    byłoby gorsze niż jego brak: powierzchnie tego repo kończą długą operację WŁASNYM zdaniem
    („Grid: 763 klatki", „Przypisano 2 z 2 klatek → M42"), więc `busy` kasujący tekst na wyjściu
    wycierałby dokładnie ten komunikat, po który user czekał. Stąd reguła doboru ujścia: faza
    dzieli kanał z raportem TYLKO tam, gdzie po niej i tak pada zdanie końcowe; gdzie nie pada —
    dostaje kanał własny (`MainWindow._phase_label`).

    Kursor wraca w `finally` — wyjątek w środku długiej operacji nie ma prawa zostawić aplikacji
    z klepsydrą na zawsze (to byłby wskaźnik, który sam udaje zawieszenie)."""
    say(text)
    repaint()
    # Kursor stawiamy STATYCZNIE (`QApplication.setOverrideCursor`), ale tylko gdy aplikacja
    # istnieje: testy logiki wołają te ścieżki bez `QApplication`, a wtedy statyczna metoda
    # wywala się na braku instancji.
    zywa = QApplication.instance() is not None
    if zywa:
        QApplication.setOverrideCursor(Qt.WaitCursor)
    try:
        yield Phase(say)
    finally:
        if zywa:
            QApplication.restoreOverrideCursor()
