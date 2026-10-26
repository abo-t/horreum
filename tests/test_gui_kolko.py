"""AR-349: kółko myszy przestawia pole wartości WYŁĄCZNIE z fokusem (`horreum.gui.kolko`), offscreen.

Dwa nośniki zdarzenia, bo każdy sięga innej połowy drogi Qt (`QApplication::notify`, gałąź `QEvent::Wheel`):
`QApplication.sendEvent` (niespontaniczne) idzie wyłącznie do odbiorcy - bez nadania fokusu wg polityki i bez
propagacji do rodzica - więc mierzy wartość pola, `isAccepted` i politykę fokusu wprost; `QTest.wheelEvent` na
`windowHandle()` (spontaniczne, przez system okien) przechodzi całą drogę: nadanie fokusu wg polityki PRZED filtrami
i pętlę doręczenia do rodzica, gdy pole zdarzenia nie przyjęło. Każdy test nazywa falsyfikator.

`importorskip` na poziomie modułu - bez PySide6 plik się pomija."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDoubleSpinBox, QInputDialog

from horreum import naming
from horreum.gui.planner import ParkDialog, PlannerView

from test_gui_planner import _seed


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


def _pompuj(n=5):
    for _ in range(n):
        QApplication.processEvents()


def _kolko(pole, dy):
    """Ząbek kółka `dy` (+120 w górę) wysłany wprost do pola - zdarzenie niespontaniczne."""
    srodek = pole.rect().center()
    ev = QWheelEvent(QPointF(srodek), QPointF(pole.mapToGlobal(srodek)), QPoint(), QPoint(0, dy), Qt.NoButton,
                     Qt.NoModifier, Qt.NoScrollPhase, False)
    QApplication.sendEvent(pole, ev)
    return ev


def _kolko_spontaniczne(pole, dy):
    """Ząbek kółka nad środkiem pola przez okno (`QTest.wheelEvent`) - pełna droga zdarzenia systemu okien."""
    okno = pole.window()
    QTest.wheelEvent(okno.windowHandle(), QPointF(pole.mapTo(okno, pole.rect().center())), QPoint(0, dy))
    _pompuj()


@pytest.fixture
def planer(qapp, tmp_path, ustawienia):
    """Planer INLINE (bez `db_path`) na bazie z trzema teleskopami, pokazany, fokus w polu „Szukaj” (klik)."""
    con = _seed(str(tmp_path / "planer.db"))
    v = PlannerView(con, db_path=None)
    v.resize(1400, 800)
    v.show()
    v.activateWindow()
    _pompuj()
    QTest.mouseClick(v.find_edit, Qt.LeftButton)
    _pompuj()
    yield v
    v.zatrzymaj_pola()           # debounce rachunku po zmianie progu nie odpali na zamkniętym połączeniu
    v.close()
    con.close()


def _prog_zapisany(ustawienia):
    ustawienia.sync()
    return ustawienia.value("planner/min_size")


# ---------------------------------------------------------------- Planer: próg (incydent `min_size` 6 → 8)

def test_prog_planera_bez_fokusu_nie_zmienia_wartosci_ani_ustawien(planer, ustawienia):
    """Ząbek kółka nad progiem „rozmiar” bez fokusu na nim: wartość 6, w `QSettings` żadnego wpisu, zdarzenie
    nieprzyjęte (idzie do rodzica), polityka `StrongFocus` (bez bitu kółka). Falsyfikatory: pole bez filtra kółka
    (wartość 7, zapis od razu); `kolko` bez `setFocusPolicy`."""
    v = planer
    assert v.find_edit.hasFocus() and v.min_size.value() == 6.0
    ev = _kolko(v.min_size, 120)
    _pompuj()
    assert v.min_size.value() == 6.0
    assert not ev.isAccepted()
    assert _prog_zapisany(ustawienia) is None
    assert v.min_size.focusPolicy() == Qt.StrongFocus


def test_prog_planera_kolko_spontaniczne_nie_kradnie_fokusu(planer, ustawienia):
    """Prawdziwa droga kółka (system okien): pole nie dostaje fokusu wg polityki i nie zmienia wartości, fokus
    zostaje w „Szukaj”, próg nie trafia do `QSettings`. Falsyfikator: `kolko` bez `StrongFocus` - Qt daje fokus
    PRZED filtrem (`giveFocusAccordingToFocusPolicy`), filtr widzi pole z fokusem i przepuszcza zmianę."""
    v = planer
    _kolko_spontaniczne(v.min_size, 120)
    assert v.min_size.value() == 6.0
    assert v.find_edit.hasFocus() and not v.min_size.hasFocus()
    assert _prog_zapisany(ustawienia) is None


def test_prog_planera_z_fokusem_dziala_jak_dzis(planer, ustawienia):
    """Z fokusem (klik w pole) kółko zmienia próg i zapisuje go od razu - funkcja zostaje. Falsyfikator: filtr,
    który zatrzymuje kółko także przy fokusie."""
    v = planer
    QTest.mouseClick(v.min_size, Qt.LeftButton)
    _pompuj()
    assert v.min_size.hasFocus()
    ev = _kolko(v.min_size, 120)
    _pompuj()
    assert v.min_size.value() == 7.0 and ev.isAccepted()
    assert float(_prog_zapisany(ustawienia)) == 7.0


def test_prog_planera_kolko_spontaniczne_z_fokusem_dziala(planer, ustawienia):
    """Prawdziwa droga kółka (system okien) z fokusem na polu (klik): odbiorcą jest wewnętrzne pole linii spinboxu,
    zdarzenie dochodzi do pola, filtr widzi fokus przez `focusProxy` i przepuszcza - próg rośnie, fokus zostaje,
    wartość trafia do `QSettings`. Falsyfikator: filtr zatrzymujący kółko bez względu na fokus."""
    v = planer
    QTest.mouseClick(v.min_size, Qt.LeftButton)
    _pompuj()
    assert v.min_size.hasFocus()
    _kolko_spontaniczne(v.min_size, 120)
    assert v.min_size.value() == 7.0 and v.min_size.hasFocus()
    assert float(_prog_zapisany(ustawienia)) == 7.0


def test_kolko_w_otwartej_liscie_combo_przewija_liste(qapp):
    """Otwarta lista combo (Alt+strzałka w dół) przewija się kółkiem jak dotąd: filtr stoi na polu, a lista to
    osobne okno wyskakujące, do którego pole kółka nie dostaje. Wybór pola bez zmian, lista dalej otwarta.
    Falsyfikator: reguła na liście combo, która zatrzymuje jej kółko (np. liczona po fokusie POLA - przy otwartej
    liście fokus ma lista, nie pole). Filtr `kolko` postawiony na samej liście jest równoważny: jej `viewport`
    oddaje fokus listy przez `focusProxy`, więc warunek fokusu przepuszcza kółko."""
    from PySide6.QtWidgets import QComboBox, QVBoxLayout, QWidget
    from horreum.gui.kolko import kolko
    okno = QWidget()
    lay = QVBoxLayout(okno)
    combo = kolko(QComboBox())
    combo.setStyleSheet("QComboBox { combobox-popup: 0; }")   # lista z sufitem wierszy (wzór `assign_dialog`)
    combo.setMaxVisibleItems(8)
    combo.addItems([f"pozycja {i}" for i in range(40)])
    lay.addWidget(combo)
    okno.resize(300, 120)
    okno.show()
    okno.activateWindow()
    _pompuj()
    try:
        QTest.keyClick(combo, Qt.Key_Down, Qt.AltModifier)
        _pompuj()
        lista = combo.view()
        assert lista.isVisible()
        pasek = lista.verticalScrollBar()
        assert pasek.maximum() > 0 and pasek.value() == 0, "lista bez przewijania - test bez przedmiotu"
        przed = combo.currentIndex()
        popup = lista.window()
        QTest.wheelEvent(popup.windowHandle(), QPointF(lista.viewport().mapTo(popup, lista.viewport().rect().center())),
                         QPoint(0, -120))
        _pompuj()
        assert pasek.value() > 0
        assert lista.isVisible() and combo.currentIndex() == przed
    finally:
        combo.hidePopup()
        okno.close()


# ---------------------------------------------------------------- okno „Park…”: zapis `telescope.parked` z kółka

def _zdarzenia_parku(con):
    return con.execute("SELECT count(*) FROM event WHERE verb = 'telescope.parked'").fetchone()[0]


@pytest.mark.parametrize("droga", ["sendEvent", "spontaniczna"])
def test_park_kolko_bez_fokusu_nie_zapisuje(planer, droga):
    """Combo stanu parku w komórce tabeli: ząbek W GÓRĘ z pozycji „nie wypowiedziałeś się” (ostatnia - ząbek w dół
    niczego by nie zmienił) bez fokusu na combo nie zmienia stanu i nie zapisuje `telescope.parked`. Kontrola
    przesłanki w tym samym oknie: ten sam ząbek na combo Z FOKUSEM zmienia stan i zapisuje zdarzenie. Falsyfikator:
    combo parku bez `kolko` (ślad na kopii pf4: 2026-08-03 siedem teleskopów `null → 0` w 74 ms)."""
    from horreum.gui.planner import _PARK_UNSAID
    v = planer
    dlg = ParkDialog(v.con, v._now)
    dlg.resize(800, 400)
    dlg.show()
    dlg.activateWindow()
    _pompuj()
    try:
        bez, z = (dlg.table.cellWidget(r, ParkDialog.COL_PARK) for r in (0, 1))
        for combo in (bez, z):
            assert combo.currentData() == _PARK_UNSAID and combo.currentIndex() == combo.count() - 1
        wyslij = _kolko if droga == "sendEvent" else _kolko_spontaniczne
        przed = _zdarzenia_parku(v.con)
        assert not bez.hasFocus()
        wyslij(bez, 120)
        _pompuj()
        assert bez.currentData() == _PARK_UNSAID and dlg.changed == 0
        assert _zdarzenia_parku(v.con) == przed
        # Kontrola: fokus na combo (klik otworzyłby listę, więc fokus wprost) - ten sam ząbek działa i zapisuje.
        z.setFocus(Qt.OtherFocusReason)
        _pompuj()
        assert z.hasFocus()
        wyslij(z, 120)
        _pompuj()
        assert z.currentData() == 0 and dlg.changed == 1
        assert _zdarzenia_parku(v.con) == przed + 1
    finally:
        dlg.reject()
        dlg.close()


# ---------------------------------------------------------------- przewijany wzór nazwy: kółko idzie do rodzica

def test_kolko_nad_wzorem_nazwy_przewija_rodzica(qapp):
    """Wzór nazwy dłuższy niż sufit przewijanego obszaru (`_TemplateEditor._scroll`): ząbek w dół nad typem tokenu
    pierwszego wiersza przewija wzór i nie zmienia tokenu. Falsyfikator: filtr bez `ignore()` - zdarzenie
    przyjęte, pętla doręczenia Qt nie dochodzi do obszaru przewijanego."""
    from horreum.gui.grid_panels import RenameBar
    bar = RenameBar()
    bar.resize(1300, 700)
    edytor = bar.template_editor
    edytor.set_template(list(naming.DEFAULT_TEMPLATE) * 2)
    bar.show()
    bar.activateWindow()
    _pompuj()
    try:
        pasek = edytor._scroll.verticalScrollBar()
        assert pasek.maximum() > 0 and pasek.value() == 0, "wzór bez przewijania - test bez przedmiotu"
        combo = edytor._rows()[0].combo
        assert not combo.hasFocus()
        przed = combo.currentData()
        _kolko_spontaniczne(combo, -120)
        assert combo.currentData() == przed
        assert pasek.value() > 0
    finally:
        bar.close()


# ---------------------------------------------------------------- pola poza konstruktorem i kolejność budowy

def test_combo_edytowalne_trzyma_strongfocus(qapp):
    """Combo edytowalne (wiersz filtra, keyword makra) po `setEditable(True)` zostaje przy `StrongFocus` - Qt
    przestawia politykę combo edytowalnego wyłącznie na macOS. Falsyfikator: polityka ustawiana przed budową pola
    linii w systemie, który ją nadpisuje."""
    from horreum.gui.grid_panels import FilterPanel, MacroBar
    panel = FilterPanel(["OBJECT", "FILTER"])
    kw = panel._rows[0]["kw"]
    makro = MacroBar(["OBJECT"])
    assert kw.isEditable() and kw.focusPolicy() == Qt.StrongFocus
    assert makro.asg_kw.isEditable() and makro.asg_kw.focusPolicy() == Qt.StrongFocus


def test_pole_odniesienia_czasu_w_oknie_qt_pod_regula_kolka(qapp, monkeypatch):
    """„Odniesienie czasu…” rodowodu: pole liczby powstaje w oknie Qt (`QInputDialog`, tryb `DoubleInput`), więc
    bramka AST go nie widzi - reguła kółka idzie na nie wprost. Kółko bez fokusu nie zmienia wartości.
    Falsyfikator: `_ask_offset` bez `kolko(okno.findChild(QDoubleSpinBox))`."""
    from horreum.gui.grid_lineage import LineageBar
    okna = []
    monkeypatch.setattr(QInputDialog, "exec", lambda self: (okna.append(self), 0)[1])
    bar = LineageBar()
    bar._ask_offset()
    assert len(okna) == 1
    pole = okna[0].findChild(QDoubleSpinBox)
    assert pole.focusPolicy() == Qt.StrongFocus
    przed = pole.value()
    ev = _kolko(pole, 120)
    assert pole.value() == przed and not ev.isAccepted()
