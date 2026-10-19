"""Prawdziwy prawy klik w testach GUI (AR-254) - jeden wzór dla pól zdania i każdego widżetu z menu.

Syntetyczne `QContextMenuEvent` wysłane `sendEvent` prosto do pola omija drogę myszy: pole przezroczyste
dla myszy (`WA_TransparentForMouseEvents`) albo zasłonięte i tak dostaje menu (zmierzone: menu jest przy
syntetyku, brak przy prawdziwym kliku). `QTest.mouseClick` prawym na samym widżecie doręcza wyłącznie
mysz - 0 zdarzeń menu. Droga człowieka to zdarzenie myszy przez okno najwyższego poziomu (`QWindow`),
z którego Qt sam składa `QContextMenuEvent` (wzór testów AR-243).

WYZWALACZ MENU (`QStyleHints.contextMenuTrigger`) zależy od platformy: natywnie na Windows `Release`,
na `offscreen` (bateria) `Press`. Przy `Press` pole z kontrolą tekstu (zaznaczalne albo z zaznaczeniem)
przyjmuje wciśnięcie i menu nie powstaje wcale (zmierzone: `[Press, Release]`, 0 zdarzeń `ContextMenu`),
choć natywnie powstaje. Pomocnik przypina na czas gestu wartość Windows i przywraca poprzednią - test
mierzy drogę produktu, nie artefakt platformy testów. API: Qt >= 6.8 - na starszym PySide6 (pakiet
deklaruje `>=6.5`) gest bez przypięcia mierzyłby artefakt, więc test z prawdziwym klikiem jest POMIJANY
z powodem, nie wykonywany ani nie wywracany asercją. Rozstrzyga WERSJA Qt (`przypiecie_wyzwalacza`), nie
obecność atrybutu: Qt >= 6.8 bez API przypięcia to błąd testu, nie pominięcie - inaczej zmiana nazwy API
schowałaby testy prawdziwego kliku jako SKIP.

Pole najwyższego poziomu nie odróżnia drogi myszy od syntetyku (okno to samo pole) - test, który chce
dowodu drogi, osadza pole w oknie-rodzicu.

Moduł bez przedrostka `test_` (pytest go nie zbiera), import jak `fixture_s8`."""
import time

import pytest
from PySide6.QtCore import QCoreApplication, QEventLoop, QPoint, Qt, qVersion
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

_CZEKAJ_NA_MENU_S = 0.3      # gest bez menu kosztuje tyle; menu Qt przychodzi w pierwszym obrocie pętli
_BEZPIECZNIK_S = 5.0


def _petla(warunek, s):
    """Pętla zdarzeń do warunku albo do końca czasu `s` - `processEvents` + `sleep`, nie `qWait`.
    Zwraca wynik warunku (bez wyjątku: brak menu bywa oczekiwanym wynikiem gestu)."""
    koniec = time.monotonic() + s
    while not warunek():
        if time.monotonic() > koniec:
            return False
        QCoreApplication.processEvents(QEventLoop.AllEvents, 20)
        time.sleep(0.005)
    return True


def przypiecie_wyzwalacza():
    """`QStyleHints` z API przypięcia wyzwalacza menu albo `pytest.skip` z powodem na Qt < 6.8. Qt >= 6.8
    bez `setContextMenuTrigger` = błąd testu (EXPECT), nie pominięcie."""
    hints = QGuiApplication.styleHints()
    if tuple(int(x) for x in qVersion().split(".")[:2]) < (6, 8):
        pytest.skip("prawdziwy prawy klik wymaga QStyleHints.setContextMenuTrigger, Qt >= 6.8")
    assert hasattr(hints, "setContextMenuTrigger"), f"Qt {qVersion()} bez QStyleHints.setContextMenuTrigger"
    return hints


def prawy_klik(widzet, punkt=None):
    """PRAWDZIWY prawy klik w `punkt` widżetu (domyślnie (5, połowa wysokości)): mysz przez uchwyt okna
    najwyższego poziomu, pozycja przez współrzędne ekranu (`mapToGlobal` → `mapFromGlobal`), wyzwalacz
    menu przypięty do `Release` na czas gestu. Czeka pętlą na menu wyskakujące (krótko - gest bez menu to
    też wynik) i zwraca aktywne menu albo None.

    EXPECT: okno pokazane (uchwyt jest), żadne menu nie jest otwarte przed gestem (klik przy otwartym
    menu tylko je zamyka - test mierzyłby poprzedni gest). Qt < 6.8 (brak przypięcia wyzwalacza) -
    `pytest.skip` z powodem (`przypiecie_wyzwalacza`)."""
    hints = przypiecie_wyzwalacza()
    uchwyt = widzet.window().windowHandle()
    assert uchwyt is not None, f"okno widżetu niepokazane - brak uchwytu: {widzet!r}"
    assert QApplication.activePopupWidget() is None, "przed gestem otwarte menu - zamknij je najpierw"
    punkt = punkt if punkt is not None else QPoint(5, widzet.height() // 2)
    poprzedni = hints.contextMenuTrigger()
    hints.setContextMenuTrigger(Qt.ContextMenuTrigger.Release)
    try:
        QTest.mouseClick(uchwyt, Qt.RightButton, Qt.NoModifier,
                         uchwyt.mapFromGlobal(widzet.mapToGlobal(punkt)))
        _petla(lambda: QApplication.activePopupWidget() is not None, _CZEKAJ_NA_MENU_S)
    finally:
        hints.setContextMenuTrigger(poprzedni)
    return QApplication.activePopupWidget()


def menu_pola_otwarte(pole):
    """Akcje menu własnego pola zdania (`EtykietaBledu._menu`), które gest otworzył NA TYM polu - aktywne
    menu wyskakujące to menu pola (czekanie pętlą do bezpiecznika): `{tekst pozycji: QAction}`."""
    otwarte = _petla(lambda: pole._menu is not None and QApplication.activePopupWidget() is pole._menu,
                     _BEZPIECZNIK_S)
    assert otwarte, (pole, pole._menu, QApplication.activePopupWidget())
    return {a.text(): a for a in pole._menu.actions()}
