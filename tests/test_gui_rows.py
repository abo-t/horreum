"""Delegat wiersza wieloczłonowego (`gui/rows.py`, P1 polish) — testy STERUJĄCE realnym Qt (offscreen).
`importorskip` na poziomie modułu (§9.4): bez PySide6 plik się POMIJA."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from horreum.gui import rows, theme

from PySide6.QtCore import QRect
from PySide6.QtGui import QBrush, QColor, QFontMetrics, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QListWidget, QListWidgetItem, QStyleOptionViewItem


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


def _list_with(text, secondary, *, strong=False, tertiary=None, indent=None):
    lw = QListWidget()
    lw.setItemDelegate(rows.TwoPartDelegate(lw, strong=strong))
    it = QListWidgetItem(text)
    if secondary is not None:
        it.setData(rows.SECONDARY, secondary)
    if tertiary is not None:
        it.setData(rows.TERTIARY, tertiary)
    if indent is not None:
        it.setData(rows.INDENT, indent)
    lw.addItem(it)
    return lw, it


def test_size_hint_nie_rosnie_od_czlonu_drugiego(qapp):
    """RDZEŃ znaleziska wiz F7 #F1: człon drugi NIE może dyktować szerokości wiersza. Gdy godziny
    szły tekstem, najdłuższy wiersz (kometa Tsuchinshan-ATLAS) przepychał listwę przez 220 px
    w poziomy scrollbar i „1.5 h" bywało ucięte. Delegat rysuje go w wolnym miejscu — `sizeHint`
    zostaje szerokością SAMEJ nazwy, a niedomiar zjada elizja."""
    lw_bez, it_bez = _list_with("Tsuchinshan-ATLAS", None)
    lw_z, it_z = _list_with("Tsuchinshan-ATLAS", "(120) · 137.5 h")
    d = lw_z.itemDelegate()
    opt = QStyleOptionViewItem()
    w_bez = lw_bez.itemDelegate().sizeHint(opt, lw_bez.model().index(0, 0)).width()
    w_z = d.sizeHint(opt, lw_z.model().index(0, 0)).width()
    assert w_z == w_bez
    # falsyfikator: gdyby człon drugi wrócił do TEKSTU wiersza, szerokość by urosła — inaczej test
    # przechodziłby też dla zepsutej implementacji (sizeHint stale 0).
    lw_stary, _ = _list_with("Tsuchinshan-ATLAS (120) · 137.5 h", None)
    assert lw_stary.itemDelegate().sizeHint(opt, lw_stary.model().index(0, 0)).width() > w_bez


def test_paint_rysuje_wszystkie_czlony(qapp):
    """Smoke rysowania (offscreen): `paint` na realnym QPainter przechodzi dla obu wariantów
    `strong`, dla wiersza BEZ członu drugiego (rola nieustawiona → sam człon pierwszy) i dla członu
    TRZECIEGO — także gdy konsument nie zawołał `fit_tertiary` (wtedy wiersz bierze własną szerokość:
    niewyrównany, ale nigdy nachodzący na liczbę)."""
    for strong in (False, True):
        for second, third in (("(12)", "· 3.0 h"), ("(12)", None), (None, "· 3.0 h"), (None, None)):
            lw, _it = _list_with("M51", second, strong=strong, tertiary=third)
            lw.resize(200, 40)
            pm = QPixmap(200, 20)
            painter = QPainter(pm)
            opt = QStyleOptionViewItem()
            opt.rect = pm.rect()
            lw.itemDelegate().paint(painter, opt, lw.model().index(0, 0))
            painter.end()


def test_czlon_drugi_bierze_kolor_wiersza_gdy_ten_niesie_znaczenie(qapp):
    """Wizytator P1 #1/#5: szarość drugorzędna jest DOBRA dla adnotacji, a KŁAMIE, gdy kolor wiersza
    coś znaczy. Trzy takie sytuacje: wiersz zaznaczony (szare „(15559)" na tle Highlight ma ~1.8:1
    kontrastu — licznik znika dokładnie tam, gdzie user wskazuje), item z JAWNYM `ForegroundRole`
    (czerwień ⊖ facetów — „(+325 ukryte)" to TREŚĆ, nie adnotacja; wyszarzenie zadania z n=0 ma objąć
    cały wiersz) oraz `strong` (liczba jest treścią z definicji)."""
    lw, it = _list_with("EXPTIME", "(15559)")
    d, idx = lw.itemDelegate(), lw.model().index(0, 0)
    assert not d._own_color(idx, selected=False)          # zwykły wiersz → szarość drugorzędna
    assert d._own_color(idx, selected=True)               # zaznaczony → HighlightedText
    it.setForeground(QColor("#FF6E6E"))                   # jak wykluczenie ⊖ w facetach
    assert d._own_color(idx, selected=False)
    lw_strong, _ = _list_with("Teleskopy bez etykiety", "4  ›", strong=True)
    assert lw_strong.itemDelegate()._own_color(lw_strong.model().index(0, 0), selected=False)


def test_zdjecie_foregroundu_wraca_do_szarosci(qapp):
    """SZEW: `FacetRail.refresh_theme` i `TasksView.refresh_counts` ZDEJMUJĄ kolor pustym `QBrush()`.
    Gdyby Qt trzymało taki brush jako wartość, `_own_color` uznałoby wiersz za pokolorowany i po
    pierwszym przełączeniu motywu godziny w listwie facetów przestałyby być drugorzędne. Qt6
    odrzuca pusty brush (`data()` → None) — test pinuje to zachowanie, bo cała reguła na nim stoi."""
    lw, it = _list_with("M51", "(5) · 1.0 h")
    d, idx = lw.itemDelegate(), lw.model().index(0, 0)
    it.setForeground(QColor("#FF6E6E"))
    assert d._own_color(idx, selected=False)
    it.setForeground(QBrush())                            # jak `refresh_theme` na wierszu nie-⊖
    assert not d._own_color(idx, selected=False)


def test_kolumna_trzeciego_czlonu_stabilizuje_prawy_brzeg_liczby(qapp):
    """Wizytator P1 #4: gdy godziny szły w tym samym runie co „(n)", zmienna szerokość ogona
    przesuwała licznik — na żywej pf4 „(301) · 60.4 h" kończyło „(n)" 108 px od prawej, a
    „(60) · 3.0 h" 96 px, więc kolumny liczb nie dało się skanować. Trzeci człon dostaje WSPÓLNĄ
    szerokość z `fit_tertiary` (najszersza adnotacja LISTY), więc prawy brzeg liczby jest ten sam
    dla wszystkich wierszy — niezależnie od tego, ile cyfr mają godziny."""
    lw = QListWidget()
    d = rows.TwoPartDelegate(lw)
    lw.setItemDelegate(d)
    assert d._tertiary_w == 0                       # lista bez adnotacji = układ dwuczłonowy
    szerokosc = d.fit_tertiary([" · 60.4 h", " · 3.0 h", " · 1.5 h"])
    fm = QFontMetrics(lw.font())
    assert szerokosc == fm.horizontalAdvance(" · 60.4 h")    # kolumna = NAJSZERSZA adnotacja listy
    assert szerokosc > fm.horizontalAdvance(" · 3.0 h")      # …a nie pierwsza/ostatnia z brzegu
    # Ogon „(+n bez exptime)" poszerza kolumnę dla CAŁEJ listy, zamiast rozjeżdżać jeden wiersz —
    # dlatego mierzymy z treści, a nie ze stałej referencyjnej (nie ma przypadku przepełnienia).
    assert d.fit_tertiary([" · 1.0 h (+5 bez exptime)", " · 3.0 h"]) > szerokosc
    assert d.fit_tertiary([]) == 0                  # pusta lista adnotacji → kolumna znika


def test_wiersz_najszerszy_nie_traci_miejsca_na_nazwe(qapp):
    """CENA rozdzielenia członów (wiz P1 #4). Kolumna rezerwuje szerokość NAJSZERSZEJ adnotacji
    w każdym wierszu, więc nazwa musi za to zapłacić — ale wiersz najszerszy nie płaci NIC: jego
    „(301) · 60.4 h" zajmuje dokładnie tyle, co przed rozdzieleniem. Warunek: separator siedzi
    W adnotacji, a delegat NIE dokłada własnego `_GAP` za kolumną (dokładany kosztowałby 9 px
    w każdym wierszu — zmierzone, Segoe UI 9 pt). Test pinuje tę arytmetykę, bo cała decyzja
    projektowa na niej stoi."""
    lw = QListWidget()
    d = rows.TwoPartDelegate(lw)
    fm = QFontMetrics(lw.font())
    kolumna = d.fit_tertiary([" · 60.4 h", " · 1.5 h"])
    sklejone = fm.horizontalAdvance("(301) · 60.4 h") + rows._GAP      # układ SPRZED rozdzielenia
    rozdzielone = kolumna + fm.horizontalAdvance("(301)") + rows._GAP  # układ po
    assert rozdzielone == sklejone
    # …a wiersz WĘŻSZY oddaje dokładnie różnicę adnotacji — to jest nieunikniona cena kolumny.
    wezszy = kolumna + fm.horizontalAdvance("(60)") + rows._GAP
    assert wezszy - (fm.horizontalAdvance("(60) · 1.5 h") + rows._GAP) == (
        fm.horizontalAdvance(" · 60.4 h") - fm.horizontalAdvance(" · 1.5 h"))


def test_strong_jest_rola_per_wiersz(qapp):
    """Wizytator P1 #6: `strong` było ustawieniem CAŁEJ listy, więc „0" na wierszu wyszarzonym
    zostawało pogrubione — pogrubienie krzyczało tam, gdzie nie ma nic do zrobienia. Rola `STRONG`
    nadpisuje wartość listy PER WIERSZ; brak roli (None) zostawia domyślną wartość listy, więc
    konsumenci, którzy jej nie ustawiają (facety, panel „Pola"), zachowują się bez zmian."""
    lw, it = _list_with("Stanowiska bez nazwy", "0  ›", strong=True)
    d, idx = lw.itemDelegate(), lw.model().index(0, 0)
    assert d._is_strong(idx)                        # rola nieustawiona → domyślna listy
    it.setData(rows.STRONG, False)
    assert not d._is_strong(idx)
    assert not d._own_color(idx, selected=False)    # …i człon drugi traci prawo do koloru wiersza
    it.setForeground(QColor("#888888"))             # ale wyszarzenie itemu (n=0) je odzyskuje
    assert d._own_color(idx, selected=False)
    lw2, it2 = _list_with("M51", "(5)")             # lista NIE-strong: rola podnosi pojedynczy wiersz
    it2.setData(rows.STRONG, True)
    assert lw2.itemDelegate()._is_strong(lw2.model().index(0, 0))


def test_use_theme_przelacza_kolor_czlonu_drugiego(qapp):
    """Kolor członu drugiego pochodzi z motywu (F6 §7, SPOT `theme.accents`) — nie jest hardcoded.
    Czytany NA ŻYWO w `paint`, więc przełączenie motywu + repaint wystarcza (bez `refresh_theme`)."""
    try:
        for name in ("dark", "light"):
            rows.use_theme(name)
            assert rows._COLORS["secondary"].name().lower() == theme.accents(name)["secondary_text"].lower()
    finally:
        rows.use_theme(theme.DEFAULT)      # przywróć globalny stan modułu dla innych testów


# ═════════════════════════ W-5 - WCIĘCIE PODWIERSZA JEST ROLĄ DELEGATA, NIE ZNAKIEM W TEKŚCIE
#
# Dawny dług: wcięcie podwiersza kolejki przeglądu żyło jako 8 spacji w `DisplayRole`
# (`app._WCIECIE`) - jechało do schowka i do wersji EN, a przy elizji zjadało miejsce nazwie.
# Rola `INDENT` (int, poziom) przenosi je do delegata: `_indent_px` liczy piksele z METRYKI FONTU
# wiersza (skaluje się z DPI/rozmiarem czcionki), `primary_rect` je stosuje do lewej krawędzi
# członu pierwszego, `paint` woła oba bez zmiany reszty zachowania.

def test_indent_px_zero_bez_poziomu(qapp):
    """Rola nieustawiona (None) i rola `0` dają 0 px - brak wcięcia jest DOMYŚLNY, nie czymś, co
    trzeba osobno wyłączyć.

    Falsyfikator: zwróć z `_indent_px` stałą > 0 niezależnie od roli → obie asercje czerwienieją."""
    lw, it = _list_with("M51", None)
    d, idx = lw.itemDelegate(), lw.model().index(0, 0)
    assert d._indent_px(idx, lw.font()) == 0
    it.setData(rows.INDENT, 0)
    assert d._indent_px(idx, lw.font()) == 0


def test_indent_px_ma_parytet_z_dawnym_wcieciem_spacjami(qapp):
    """W-5: `_indent_px` dla poziomu 1 ma dać DOKŁADNIE tę szerokość, którą dawniej zajmowało
    tekstowe `app._WCIECIE` (8 spacji) na TYM SAMYM foncie - inaczej x startu nazwy podwiersza
    rusza się i przynależność do rodzica przestaje czytać się jednym rzutem oka.

    ZMIERZONE PRZED wdrożeniem (2026-09-26, offscreen, font domyślny nowego `QListWidget()` =
    "Sans Serif" 9 pt): szerokość 8 spacji = 96 px. Liczba jest DOWODEM pomiaru, nie asercją:
    test porównuje obie strony NA ŻYWO, bo szerokość spacji zależy od fontu i platformy QPA
    (offscreen na tej maszynie nie ma bazy fontów), a bramka na piksele środowiska mierzyłaby
    fikcję i pękała między maszynami.

    Falsyfikator: zmień `_INDENT_UNIT_SPACES` w `rows.py` na inną wartość niż 8 → pierwsza asercja
    czerwienieje (parytet z dawnym wcięciem pęka)."""
    lw, _it = _list_with("M51", None, indent=1)
    d, idx = lw.itemDelegate(), lw.model().index(0, 0)
    stary_px = QFontMetrics(lw.font()).horizontalAdvance(" " * 8)     # dawny _WCIECIE, ta sama miara
    assert d._indent_px(idx, lw.font()) == stary_px
    assert d._indent_px(idx, lw.font()) > 0


def test_indent_px_rosnie_liniowo_z_poziomem(qapp):
    """Poziom 2 to DWA razy jednostka poziomu 1 - kontrakt roli jest `int`, nie `bool`, więc
    ewentualne wielopoziomowe zagnieżdżenie (dziś nieużywane) skaluje się przewidywalnie.

    Falsyfikator: podstaw w `_indent_px` `unit` stałe zamiast `level * unit` (ignorując poziom) →
    obie asercje czerwienieją, bo poziom 2 przestałby się różnić od poziomu 1."""
    lw1, _ = _list_with("M51", None, indent=1)
    lw2, _ = _list_with("M51", None, indent=2)
    d1, d2 = lw1.itemDelegate(), lw2.itemDelegate()
    px1 = d1._indent_px(lw1.model().index(0, 0), lw1.font())
    px2 = d2._indent_px(lw2.model().index(0, 0), lw2.font())
    assert px2 == 2 * px1
    assert px2 > px1 > 0


def test_primary_rect_przesuwa_lewa_krawedz_o_wciecie(qapp):
    """Mała czysta metoda GEOMETRII (bez paintera/stylu) - test mierzy x startu członu pierwszego
    bez odpalania `paint` na realnym obrazie (wymóg W-5, pomiar rysowanego tekstu jest w teście
    nieosiągalny bez realnego okna). Poziom 0/brak zostawia prostokąt CAŁKOWICIE NIETKNIĘTY -
    sierota i wiersz zwykły nie płacą niczego za samo istnienie roli. Prawa krawędź (miejsce na
    człon drugi/trzeci) jest sprawą `paint`/`tail`, nie tej metody - `primary_rect` rusza WYŁĄCZNIE
    lewą.

    Falsyfikator: zwróć z `primary_rect` goły `QRect(rect)` (zignoruj `_indent_px`) → pierwsza i
    trzecia asercja czerwienieją."""
    base = QRect(10, 0, 200, 20)
    lw0, _ = _list_with("M51", None, indent=0)
    lw1, _ = _list_with("M51", None, indent=1)
    d0, d1 = lw0.itemDelegate(), lw1.itemDelegate()
    idx0, idx1 = lw0.model().index(0, 0), lw1.model().index(0, 0)
    r0 = d0.primary_rect(base, idx0, lw0.font())
    r1 = d1.primary_rect(base, idx1, lw1.font())

    assert r1.left() > r0.left(), "wcięcie nie przesunęło lewej krawędzi członu pierwszego"
    assert r0 == base, "poziom 0 ma zostawić prostokąt CAŁKOWICIE nietknięty"
    assert r1.left() == base.left() + d1._indent_px(idx1, lw1.font())
    assert r1.right() == base.right(), "wcięcie rusza WYŁĄCZNIE lewą krawędź - prawa jest sprawą `paint`/`tail`"


def test_paint_z_wcieciem_nie_wysypuje_sie(qapp):
    """Smoke (offscreen): `paint` na realnym painterze przechodzi z rolą `INDENT` ustawioną - obok
    reszty członów i bez nich. Nie mierzy pikseli (to `primary_rect`/`_indent_px` wyżej) - pilnuje
    WYŁĄCZNIE, że dodanie roli nie wysadza rysowania.

    Falsyfikator: ten test wymaga istnienia `rows.INDENT` - bez roli (stan SPRZED W-5) `_list_with`
    rzuca `AttributeError` przy `it.setData(rows.INDENT, indent)`, więc test pada już na starcie."""
    for indent in (0, 1, 2):
        lw, _it = _list_with("NGC 7000", "(3)  ›", tertiary="  ·  cofnięte ręką", indent=indent)
        lw.resize(200, 40)
        pm = QPixmap(200, 20)
        painter = QPainter(pm)
        opt = QStyleOptionViewItem()
        opt.rect = pm.rect()
        lw.itemDelegate().paint(painter, opt, lw.model().index(0, 0))
        painter.end()
