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

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDoubleSpinBox, QInputDialog, QWidget

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


class _Trafienia(QObject):
    """Filtr notujący `QEvent.Wheel` na polu i jego potomkach (pole linii spinboxu, widok listy) - nic nie przyjmuje."""

    def __init__(self):
        super().__init__()
        self.bylo = False

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Wheel:
            self.bylo = True
        return False


def _kolko_spontaniczne(pole, dy):
    """Ząbek kółka nad środkiem pola przez okno (`QTest.wheelEvent`) - pełna droga zdarzenia systemu okien.

    Punkt W PIKSELACH NATYWNYCH (AR-369): droga kółka przez `QWindow` dzieli punkt przez skalę Qt (droga myszy przelicza
    sama), więc przy DPR 1,5 ząbek celowany w pole lądował w `pos/1,5` - u sąsiada albo w odstępie układu, a test „bez
    fokusu nie zmienia” przechodził pusto. Na Windows i offscreen cały DPR okna to skala Qt. Asercja trafienia pilnuje
    uprzęży na każdej platformie: ząbek, który nie doszedł do pola, jest błędem testu, nie zielonym wynikiem."""
    okno = pole.window()
    uchwyt = okno.windowHandle()
    straz = _Trafienia()                   # referencja w Pythonie - filtr bez właściciela znika z GC
    cele = [pole, *pole.findChildren(QWidget)]
    for w in cele:
        w.installEventFilter(straz)
    try:
        QTest.wheelEvent(uchwyt, QPointF(pole.mapTo(okno, pole.rect().center())) * uchwyt.devicePixelRatio(),
                         QPoint(0, dy))
        _pompuj()
    finally:
        for w in cele:
            w.removeEventFilter(straz)
    assert straz.bylo, f"ząbek minął pole {type(pole).__name__} (DPR {uchwyt.devicePixelRatio()})"


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
        _kolko_spontaniczne(lista.viewport(), -120)      # okno wyskakujące listy - ta sama uprząż (AR-369)
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


# ---------------------------------------------------------------- AR-369: uprząż ząbka przy DPR ≠ 1

def test_kolko_spontaniczne_pole_bez_kolka_zmienia_wartosc(qapp):
    """Kontrola przesłanki uprzęży: ten sam ząbek drogą systemu okien na GOŁYM polu (bez `kolko`, bez fokusu) zmienia
    wartość - zdarzenie doszło i działa, więc „bez fokusu nie zmienia” na polu z `kolko` nie jest pustym wynikiem.
    Falsyfikator: punkt ząbka poza polem (pole bez zmiany)."""
    from PySide6.QtWidgets import QHBoxLayout
    okno = QWidget()
    QHBoxLayout(okno).addWidget(pole := QDoubleSpinBox())
    okno.resize(300, 60)
    okno.show()
    okno.activateWindow()
    _pompuj()
    try:
        _kolko_spontaniczne(pole, 120)
        assert pole.value() == 1.0
    finally:
        okno.close()


def test_kolko_spontaniczne_mowi_gdy_zabek_minal_pole(qapp):
    """Asercja trafienia: pole przykryte rodzeństwem podniesionym nad nie - ząbek dostaje zasłona, nie pole, a pomocnik
    mówi to błędem zamiast pustego PASS. Falsyfikator: pomocnik bez asercji trafienia."""
    okno = QWidget()
    okno.resize(300, 100)
    pole = QDoubleSpinBox(okno)
    pole.setGeometry(10, 10, 120, 30)
    zaslona = QWidget(okno)
    zaslona.setGeometry(0, 0, 300, 100)
    zaslona.raise_()
    okno.show()
    okno.activateWindow()
    _pompuj()
    try:
        with pytest.raises(AssertionError, match="ząbek minął pole"):
            _kolko_spontaniczne(pole, 120)
        assert pole.value() == 0.0
    finally:
        okno.close()


def test_kolko_spontaniczne_trafia_przy_skali_150():
    """AR-369: przy DPR 1,5 (offscreen z `QT_SCALE_FACTOR=1.5` w podprocesie - czynnik skali Qt czyta przy budowie
    `QApplication`, a bateria ma jeden sesyjny) ząbek uprzęży trafia środek celowanego pola: w rzędzie sześciu gołych pól
    po 100 px zmienia się wyłącznie czwarte. Falsyfikator: punkt bez przeliczenia na piksele natywne (trafia trzecie,
    asercja trafienia pomocnika pada)."""
    import subprocess
    import sys
    import textwrap
    from pathlib import Path
    testy = Path(__file__).resolve().parent
    kod = textwrap.dedent(f"""
        import faulthandler
        import sys
        faulthandler.dump_traceback_later(60, exit=True)
        sys.path.insert(0, {str(testy)!r})
        from PySide6.QtWidgets import QApplication, QDoubleSpinBox, QHBoxLayout, QWidget
        app = QApplication([])
        from test_gui_kolko import _kolko_spontaniczne
        okno = QWidget()
        lay = QHBoxLayout(okno)
        lay.setSpacing(0)
        lay.setContentsMargins(0, 0, 0, 0)
        pola = []
        for _ in range(6):
            p = QDoubleSpinBox()
            p.setFixedSize(100, 30)
            lay.addWidget(p)
            pola.append(p)
        okno.show()
        okno.activateWindow()
        for _ in range(10):
            app.processEvents()
        try:
            _kolko_spontaniczne(pola[3], 120)
            print(okno.windowHandle().devicePixelRatio(), [p.value() for p in pola])
        finally:
            okno.close()
    """)
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QT_SCALE_FACTOR="1.5", PYTHONPATH=str(testy.parent))
    wynik = subprocess.run([sys.executable, "-c", kod], capture_output=True, text=True, env=env, timeout=120)
    assert wynik.returncode == 0, wynik.stdout + wynik.stderr
    assert wynik.stdout.strip() == "1.5 [0.0, 0.0, 0.0, 1.0, 0.0, 0.0]", wynik.stdout + wynik.stderr
