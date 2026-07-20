"""Delegat wiersza dwuczłonowego (`gui/rows.py`, P1 polish) — testy STERUJĄCE realnym Qt (offscreen).
`importorskip` na poziomie modułu (§9.4): bez PySide6 plik się POMIJA."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from horreum.gui import rows, theme

from PySide6.QtGui import QBrush, QColor, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QListWidget, QListWidgetItem, QStyleOptionViewItem


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


def _list_with(text, secondary, *, strong=False):
    lw = QListWidget()
    lw.setItemDelegate(rows.TwoPartDelegate(lw, strong=strong))
    it = QListWidgetItem(text)
    if secondary is not None:
        it.setData(rows.SECONDARY, secondary)
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


def test_paint_rysuje_oba_czlony(qapp):
    """Smoke rysowania (offscreen): `paint` na realnym QPainter przechodzi dla obu wariantów
    `strong` i dla wiersza BEZ członu drugiego (rola nieustawiona → sam człon pierwszy)."""
    for strong in (False, True):
        for second in ("(12) · 3.0 h", None):
            lw, _it = _list_with("M51", second, strong=strong)
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


def test_use_theme_przelacza_kolor_czlonu_drugiego(qapp):
    """Kolor członu drugiego pochodzi z motywu (F6 §7, SPOT `theme.accents`) — nie jest hardcoded.
    Czytany NA ŻYWO w `paint`, więc przełączenie motywu + repaint wystarcza (bez `refresh_theme`)."""
    try:
        for name in ("dark", "light"):
            rows.use_theme(name)
            assert rows._COLORS["secondary"].name().lower() == theme.accents(name)["secondary_text"].lower()
    finally:
        rows.use_theme(theme.DEFAULT)      # przywróć globalny stan modułu dla innych testów
