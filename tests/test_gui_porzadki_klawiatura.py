"""Porządki z klawiatury i wejście w Dostawę gestem „?”: Enter na wierszu listy = klik (AR-377, filtr zdarzeń, jedno
doręczenie), pętla Popraw z klawiatury (Enter na „Porządki” w sidebarze, „← Porządki” z fokusem na tym samym wierszu);
jeden rachunek kopii czekających na gest „?” i jedna migawka trzech odczytów wejścia w Dostawę (AR-379); tryb liczników
od montażu, bieg wyprzedzony i lista nieaktualna bez rachunku w drodze (AR-380). Klawiatura i mysz - prawdziwe
`QTest.keyClick`/`mouseClick`; czekanie na wątek - `processEvents` + `sleep` (pomocniki `test_gui_mainwindow`)."""
import sqlite3

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QProxyStyle, QPushButton, QStyle  # noqa: E402

from horreum import db  # noqa: E402
from horreum.gui import i18n, queries, tasks as tasks_mod  # noqa: E402
from horreum.gui.app import NAV_DOM, NAV_PORZADKI, STRONA_DOSTAWA, MainWindow  # noqa: E402
from horreum.gui.grid import PRESET_DUPS  # noqa: E402
from test_gui_mainwindow import (_BEZPIECZNIK_LICZNIKOW_S, _brama_rachunku, _czekaj_na, _klik_nav,  # noqa: E402
                                 _lista_czynna, _okno_po_montazu, _po_wyniku, _pompuj, _seeded_db, _task_item,
                                 _w_tle, _zapis_drugim_polaczeniem)

from fixture_s8 import seed_object_axis  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


def _widok(con, **kw):
    """Samodzielny `TasksView` pokazany, z przyłożonym rachunkiem (wiersze akcyjne czynne)."""
    tv = tasks_mod.TasksView(con, **kw)
    tv.resize(700, 900)
    tv.show()
    tv.refresh_counts()
    _pompuj()
    return tv


def _wiersz(tv, klucz):
    return next(tv.tasks.item(r) for r, (k, _l, _a) in enumerate(tasks_mod._TASKS) if k == klucz)


def _klik_w(tv, it, *, dwuklik=False):
    """Klik albo DWUKLIK jak z myszy: wciśnięcie, puszczenie, potem `mouseDClick` (Qt 6.9.2 wysyła w nim wyłącznie
    zdarzenie dwukliku i puszczenie - bez pierwszego kliku `clicked` nie pada, zmierzone)."""
    srodek, vp = tv.tasks.visualItemRect(it).center(), tv.tasks.viewport()
    if dwuklik:
        QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, srodek)
        QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, srodek)
        QTest.mouseDClick(vp, Qt.LeftButton, Qt.NoModifier, srodek)
    else:
        QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier, srodek)
    _pompuj()


def _wstecz(tasks):
    return next(b for b in tasks.pages.currentWidget().findChildren(QPushButton) if b.text() == i18n.t("tasks.back"))


def _bledy_haka(monkeypatch):
    """Wyjątki, które trafiły do `sys.excepthook` (slot albo wirtualna metoda wołana z pętli C++)."""
    import sys
    bledy = []
    monkeypatch.setattr(sys, "excepthook", lambda typ, exc, tb: bledy.append(exc))
    return bledy


def _enter_z_petli(widzet, klawisz=Qt.Key_Return):
    """Enter doręczony z pętli zdarzeń C++ jak w programie (`postEvent` + `QEventLoop.exec`): wyjątek filtra zdarzeń
    wołanego z `QTest.keyClick` z Pythona PySide6 6.9.2 połyka bez śladu, z pętli C++ oddaje `sys.excepthook`."""
    from PySide6.QtCore import QEventLoop, QTimer
    for typ in (QEvent.KeyPress, QEvent.KeyRelease):
        QApplication.postEvent(widzet, QKeyEvent(typ, klawisz, Qt.NoModifier, "\r"))
    petla = QEventLoop()
    QTimer.singleShot(150, petla.quit)
    petla.exec()
    _pompuj()


# ═════════════════════════ AR-377 - Enter na wierszu = klik

def test_enter_na_wierszu_porzadkow_otwiera_to_co_klik(qapp, tmp_path, monkeypatch):
    """Enter (`Key_Return` i `Key_Enter` z klawiatury numerycznej) na bieżącym wierszu listy w trybie produkcyjnym
    otwiera to samo co klik - raz na naciśnięcie; klawisz z `QTest.keyClick` i z pętli zdarzeń C++, bez wyjątku w haku.
    Dawniej nic (lista podpinała wyłącznie `itemClicked`). Mutanty: bez filtra zdarzeń; filtr tylko `Key_Return`."""
    _w_tle(monkeypatch)
    bledy = _bledy_haka(monkeypatch)
    win = MainWindow(_seeded_db(tmp_path, object_axis=True))
    try:
        tasks = _okno_po_montazu(win)
        otwarte = []
        tasks.open_collection.connect(otwarte.append)
        for klawisz, z_petli in ((Qt.Key_Return, False), (Qt.Key_Enter, False), (Qt.Key_Enter, True)):
            _klik_nav(win, NAV_PORZADKI)
            _czekaj_na(lambda: tasks._liczniki_thread is None and _lista_czynna(win), "lista czynna")
            tasks.tasks.setFocus(Qt.TabFocusReason)
            tasks.tasks.setCurrentItem(_task_item(win, "dup_frames"))
            if z_petli:
                _enter_z_petli(tasks.tasks, klawisz)
            else:
                QTest.keyClick(tasks.tasks, klawisz)
                _pompuj()
        assert otwarte == [PRESET_DUPS] * 3 and bledy == [], (otwarte, bledy)
    finally:
        win.close()


def test_enter_na_liscie_nieaktualnej_czeka_na_wynik_rachunku(qapp, tmp_path, monkeypatch):
    """Enter na wierszu WYGASZONYM (lista nieaktualna po zapisie, rachunek wejścia w tle za bramą) niczego nie otwiera
    od razu i nie przepada: po wyniku rachunku prowadzi tam, gdzie klik - tą samą drogą odłożenia (AR-337), bez drugiego
    gestu; Enter z pętli zdarzeń C++. Mutant: filtr woła `_on_task_clicked` wprost (otwiera na starych liczbach przed
    wynikiem)."""
    _w_tle(monkeypatch)
    bledy = _bledy_haka(monkeypatch)
    path = _seeded_db(tmp_path, object_axis=True)
    win = MainWindow(path)
    brama = None
    try:
        tasks = _okno_po_montazu(win)
        _klik_nav(win, NAV_PORZADKI)
        _czekaj_na(lambda: tasks._liczniki_thread is None and _lista_czynna(win), "lista czynna")
        tasks.tasks.setCurrentItem(_task_item(win, "dup_frames"))
        _klik_nav(win, NAV_DOM)
        brama, wszedl, _watki, _glowny = _brama_rachunku(monkeypatch)
        _zapis_drugim_polaczeniem(path)
        _klik_nav(win, NAV_PORZADKI)
        assert wszedl.wait(_BEZPIECZNIK_LICZNIKOW_S)
        otwarte = []
        tasks.open_collection.connect(otwarte.append)
        assert tasks.tasks.currentItem() is _task_item(win, "dup_frames")
        assert not tasks.tasks.currentItem().flags() & Qt.ItemIsEnabled, "wiersz bieżący nie jest wygaszony"
        _enter_z_petli(tasks.tasks)
        assert otwarte == []
        brama.set()
        _czekaj_na(lambda: _po_wyniku(tasks) and _lista_czynna(win), "rachunek wejścia nie przyłożony")
        _pompuj()
        assert otwarte == [PRESET_DUPS] and bledy == [], (otwarte, bledy)
    finally:
        if brama is not None:
            brama.set()
        win.close()


class _AktywacjaJednymKlikiem(QProxyStyle):
    """Styl, w którym jeden klik aktywuje element (jak motywy KDE) - Qt doręcza wtedy `clicked` I `activated`."""

    def styleHint(self, hint, opt=None, widget=None, ret=None):
        if hint == QStyle.StyleHint.SH_ItemView_ActivateItemOnSingleClick:
            return 1
        return super().styleHint(hint, opt, widget, ret)


def test_dwuklik_i_aktywacja_jednym_klikiem_otwieraja_raz(qapp):
    """Dwuklik (Qt: `clicked` + `activated`) i klik w stylu z aktywacją jednym klikiem (`clicked` + `activated` na jeden
    klik) otwierają wiersz RAZ - aktywacja nie jest drugą drogą do `_on_task_clicked`, które nie jest idempotentne.
    Kontrola: `itemActivated` naprawdę pada w obu gestach. Mutant: `itemActivated` podpięte pod `_klik_w_wiersz`."""
    con = db.open_db(":memory:")
    seed_object_axis(con)
    tv = _widok(con)
    styl = _AktywacjaJednymKlikiem()
    try:
        otwarte, aktywacje = [], []
        tv.open_collection.connect(otwarte.append)
        tv.tasks.itemActivated.connect(aktywacje.append)
        _klik_w(tv, _wiersz(tv, "dup_frames"), dwuklik=True)
        assert otwarte == [PRESET_DUPS] and len(aktywacje) == 1, (otwarte, aktywacje)
        tv.tasks.setStyle(styl)
        _klik_w(tv, _wiersz(tv, "dup_frames"))
        assert otwarte == [PRESET_DUPS, PRESET_DUPS] and len(aktywacje) == 2, (otwarte, aktywacje)
    finally:
        tv.close()
        con.close()


def test_enter_bez_biezacego_wiersza_nic_nie_robi(qapp, monkeypatch):
    """Enter na liście bez bieżącego wiersza - zero emisji, zero wyjątku z filtra (`_klik_w_wiersz(None)`), także gdy
    klawisz przychodzi z pętli zdarzeń C++ jak w programie: wyjątek wirtualnej metody wołanej z `QTest.keyClick`
    z Pythona PySide6 6.9.2 połyka bez śladu, a z pętli C++ oddaje `sys.excepthook` (zmierzone; precedens
    `test_gui_bledy_systemu._pompuj_az`). Mutant: bez strażnika `None` (`AttributeError` z filtra zdarzeń)."""
    import sys
    from PySide6.QtCore import QEventLoop, QTimer
    bledy = []
    monkeypatch.setattr(sys, "excepthook", lambda *a: bledy.append(a[1]))
    con = db.open_db(":memory:")
    seed_object_axis(con)
    tv = _widok(con)
    try:
        otwarte = []
        tv.open_collection.connect(otwarte.append)
        tv.open_intake.connect(lambda: otwarte.append("dostawa"))
        tv.tasks.setCurrentRow(-1)
        assert tv.tasks.currentItem() is None
        QTest.keyClick(tv.tasks, Qt.Key_Return)
        _pompuj()
        QApplication.postEvent(tv.tasks, QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier))
        petla = QEventLoop()
        QTimer.singleShot(200, petla.quit)
        petla.exec()
        assert otwarte == [] and bledy == [], (otwarte, bledy)
    finally:
        tv.close()
        con.close()


def test_przytrzymany_enter_otwiera_raz(qapp):
    """Przytrzymany Enter (auto-powtórzenie) na widoku, który nie zmienia strony, otwiera wiersz raz - powtórzenie
    zjedzone bez akcji. Mutant: filtr bez `isAutoRepeat`."""
    con = db.open_db(":memory:")
    seed_object_axis(con)
    tv = _widok(con)
    try:
        otwarte = []
        tv.open_collection.connect(otwarte.append)
        tv.tasks.setCurrentItem(_wiersz(tv, "dup_frames"))
        QTest.keyClick(tv.tasks, Qt.Key_Return)
        powtorzenie = QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier, "\r", True)
        QApplication.sendEvent(tv.tasks, powtorzenie)
        _pompuj()
        assert otwarte == [PRESET_DUPS], otwarte
    finally:
        tv.close()
        con.close()


# ═════════════════════════ AR-377 - pętla Popraw z klawiatury

def test_petla_popraw_z_klawiatury(qapp, tmp_path, monkeypatch):
    """Strzałki w sidebarze do „Porządki”, Enter kładzie fokus na liście zadań; strzałki na liście do wiersza, Enter
    otwiera podstronę; spacja na „← Porządki” wraca na listę z fokusem na TYM SAMYM wierszu - następny wiersz bez Tab.
    Enter z pętli zdarzeń C++, bez wyjątku w haku. Mutant: `_on_nav_wejscie` bez gałęzi Porządków."""
    from horreum.gui import tasks as tm
    _w_tle(monkeypatch)
    bledy = _bledy_haka(monkeypatch)
    win = MainWindow(_seeded_db(tmp_path, object_axis=True))
    try:
        tasks = _okno_po_montazu(win)
        win.nav.setFocus(Qt.TabFocusReason)
        for _ in range(NAV_PORZADKI):                  # z Domu: Znajdź, Dostawa, Zbiory, Porządki (nagłówek omijany)
            if win.nav.currentRow() == NAV_PORZADKI:
                break
            QTest.keyClick(win.nav, Qt.Key_Down)
            _pompuj()
        assert win.nav.currentRow() == NAV_PORZADKI
        _czekaj_na(lambda: tasks._liczniki_thread is None and _lista_czynna(win), "lista czynna")
        _enter_z_petli(win.nav)
        assert QApplication.activeWindow() is win and tasks.tasks.hasFocus(), QApplication.focusWidget()
        wiersz = _task_item(win, "telescopes_unlabeled")
        for _ in range(tasks.tasks.count()):
            if tasks.tasks.currentItem() is wiersz:
                break
            QTest.keyClick(tasks.tasks, Qt.Key_Down)
        assert tasks.tasks.currentItem() is wiersz
        _enter_z_petli(tasks.tasks)
        assert tasks.pages.currentIndex() == tm._PAGE_TELESCOPE
        wstecz = _wstecz(tasks)
        wstecz.setFocus(Qt.TabFocusReason)
        QTest.keyClick(wstecz, Qt.Key_Space)
        _pompuj()
        assert tasks.pages.currentIndex() == tm._PAGE_LIST
        assert tasks.tasks.hasFocus() and tasks.tasks.currentItem() is wiersz
        assert bledy == [], bledy
    finally:
        win.close()


def test_klik_w_porzadki_nie_przenosi_fokusu_na_liste(qapp, tmp_path, monkeypatch):
    """Klik myszą w „Porządki” zostawia fokus w sidebarze - lista z fokusem pokazuje natywną obwódkę bieżącego wiersza,
    a dla myszy byłby to nowy stan po każdym wejściu (fokus listy wyłącznie z klawiatury). Mutant: gałąź Porządków
    bez warunku klawisza."""
    _w_tle(monkeypatch)
    win = MainWindow(_seeded_db(tmp_path, object_axis=True))
    try:
        tasks = _okno_po_montazu(win)
        _klik_nav(win, NAV_PORZADKI)
        assert win.nav.hasFocus() and not tasks.tasks.hasFocus(), QApplication.focusWidget()
    finally:
        win.close()


def test_dwuklik_w_porzadki_nie_przenosi_fokusu_na_liste(qapp, tmp_path, monkeypatch):
    """Dwuklik myszą w „Porządki” aktywuje wiersz paska (`itemActivated`) jak Enter - ale to mysz: fokus zostaje
    w pasku (przycisk myszy wciśnięty w chwili aktywacji z dwukliku, przy Enterze nie). Mutant: adapter aktywacji
    zawsze ze znacznikiem klawisza."""
    _w_tle(monkeypatch)
    win = MainWindow(_seeded_db(tmp_path, object_axis=True))
    try:
        tasks = _okno_po_montazu(win)
        aktywacje = []
        win.nav.itemActivated.connect(aktywacje.append)
        srodek, vp = win.nav.visualItemRect(win.nav.item(NAV_PORZADKI)).center(), win.nav.viewport()
        QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, srodek)
        QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, srodek)
        QTest.mouseDClick(vp, Qt.LeftButton, Qt.NoModifier, srodek)
        _pompuj()
        assert len(aktywacje) == 1, "dwuklik nie aktywował wiersza paska"
        assert win.nav.hasFocus() and not tasks.tasks.hasFocus(), QApplication.focusWidget()
    finally:
        win.close()


def test_enter_na_porzadkach_przy_podstronie_kladzie_fokus_na_powrot(qapp, tmp_path, monkeypatch):
    """Porządki zostały na podstronie osi (lista schowana): strzałka do „Porządki” w pasku i Enter kładą fokus na
    „← Porządki” podstrony, nie na schowanej liście - drugi Enter wraca na listę i nie otwiera wiersza, którego
    człowiek nie widział (AR-415). Mutant: fokus na liście bez względu na stronę."""
    from horreum.gui import tasks as tm
    _w_tle(monkeypatch)
    bledy = _bledy_haka(monkeypatch)
    win = MainWindow(_seeded_db(tmp_path, object_axis=True))
    try:
        tasks = _okno_po_montazu(win)
        _klik_nav(win, NAV_PORZADKI)
        _czekaj_na(lambda: tasks._liczniki_thread is None and _lista_czynna(win), "lista czynna")
        QTest.mouseClick(tasks.tasks.viewport(), Qt.LeftButton, Qt.NoModifier,
                         tasks.tasks.visualItemRect(_task_item(win, "telescopes_unlabeled")).center())
        _pompuj()
        assert tasks.pages.currentIndex() == tm._PAGE_TELESCOPE
        tasks.tasks.setCurrentItem(_task_item(win, "dup_frames"))   # bieżący schowanej listy otwiera Zbiory
        _klik_nav(win, NAV_DOM)
        win.nav.setFocus(Qt.TabFocusReason)
        for _ in range(NAV_PORZADKI):                                 # Dom → Znajdź → Dostawa → Zbiory → Porządki
            if win.nav.currentRow() == NAV_PORZADKI:
                break
            QTest.keyClick(win.nav, Qt.Key_Down)
            _pompuj()
        assert win.nav.currentRow() == NAV_PORZADKI and tasks.pages.currentIndex() == tm._PAGE_TELESCOPE
        otwarte = []
        tasks.open_collection.connect(otwarte.append)
        tasks.open_intake.connect(lambda: otwarte.append("dostawa"))
        tasks.open_object_change_run.connect(otwarte.append)
        _enter_z_petli(win.nav)
        fokus = QApplication.focusWidget()
        assert fokus is _wstecz(tasks) and fokus.isVisible(), fokus
        _enter_z_petli(fokus)
        assert otwarte == [] and tasks.pages.currentIndex() == tm._PAGE_LIST and bledy == [], (otwarte, bledy)
        assert tasks.tasks.hasFocus() and tasks.tasks.currentItem() is _task_item(win, "dup_frames")
    finally:
        win.close()


def test_enter_na_powrocie_wraca_na_ten_sam_wiersz(qapp, tmp_path, monkeypatch):
    """Enter (`Key_Return` i `Key_Enter` z klawiatury numerycznej, z `QTest.keyClick` i z pętli zdarzeń C++) na
    „← Porządki” z fokusem wraca na listę z fokusem na wierszu, z którego człowiek wszedł - jak Spacja i klik. Dawniej
    nic: przycisk poza oknem dialogowym reaguje wyłącznie na Spację (AR-415). Przycisk z fokusem nie staje się domyślny
    - `autoDefault` zmieniłby jego rysunek w Fusion. Przytrzymany Enter wraca raz: auto-powtórzenia trafiają już w listę
    i niczego nie otwierają. Mutanty: zwykły `QPushButton` w `_wrap`; `setAutoDefault(True)` zamiast obsługi klawisza."""
    from horreum.gui import tasks as tm
    _w_tle(monkeypatch)
    bledy = _bledy_haka(monkeypatch)
    win = MainWindow(_seeded_db(tmp_path, object_axis=True))
    try:
        tasks = _okno_po_montazu(win)
        _klik_nav(win, NAV_PORZADKI)
        _czekaj_na(lambda: tasks._liczniki_thread is None and _lista_czynna(win), "lista czynna")
        wiersz = _task_item(win, "telescopes_unlabeled")
        otwarte = []
        tasks.open_collection.connect(otwarte.append)
        tasks.open_intake.connect(lambda: otwarte.append("dostawa"))
        tasks.open_object_change_run.connect(otwarte.append)
        for klawisz, z_petli in ((Qt.Key_Return, False), (Qt.Key_Enter, False), (Qt.Key_Return, True)):
            _czekaj_na(lambda: tasks._liczniki_thread is None and _lista_czynna(win), "lista czynna")
            tasks.tasks.setFocus(Qt.TabFocusReason)
            tasks.tasks.setCurrentItem(wiersz)
            QTest.keyClick(tasks.tasks, Qt.Key_Return)
            _pompuj()
            assert tasks.pages.currentIndex() == tm._PAGE_TELESCOPE
            wstecz = _wstecz(tasks)
            wstecz.setFocus(Qt.TabFocusReason)
            _pompuj()
            assert wstecz.hasFocus() and not wstecz.autoDefault() and not wstecz.isDefault()
            if z_petli:
                _enter_z_petli(wstecz, klawisz)
            else:
                QTest.keyClick(wstecz, klawisz)
                _pompuj()
            assert tasks.pages.currentIndex() == tm._PAGE_LIST, (klawisz, z_petli)
            assert tasks.tasks.hasFocus() and tasks.tasks.currentItem() is wiersz, QApplication.focusWidget()
        tasks.tasks.setCurrentItem(wiersz)
        QTest.keyClick(tasks.tasks, Qt.Key_Return)
        _pompuj()
        wstecz = _wstecz(tasks)
        wstecz.setFocus(Qt.TabFocusReason)
        QApplication.sendEvent(wstecz, QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier, "\r"))
        for _ in range(3):                                   # auto-powtórzenia trafiają w widżet z fokusem
            QApplication.sendEvent(QApplication.focusWidget(),
                                   QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier, "\r", True))
        QApplication.sendEvent(QApplication.focusWidget(), QKeyEvent(QEvent.KeyRelease, Qt.Key_Return, Qt.NoModifier))
        _pompuj()
        assert tasks.pages.currentIndex() == tm._PAGE_LIST and tasks.tasks.currentItem() is wiersz
        assert otwarte == [] and bledy == [], (otwarte, bledy)
    finally:
        win.close()


def test_enter_na_porzadkach_bez_biezacego_bierze_pierwszy_wiersz_akcyjny(qapp, tmp_path, monkeypatch):
    """Lista nieaktualna (rachunek wejścia za bramą) bez bieżącego wiersza: Enter na „Porządki” kładzie fokus na liście
    z bieżącym PIERWSZYM WIERSZEM AKCYJNYM (wygaszonym) - Enter na nim czeka na wynik i otwiera jego podstronę. Sam Qt
    wybrałby przy fokusie pierwszy wiersz czynny, czyli informacyjny. Mutant: bez wyboru pierwszego wiersza
    akcyjnego."""
    from horreum.gui import tasks as tm
    _w_tle(monkeypatch)
    bledy = _bledy_haka(monkeypatch)
    path = _seeded_db(tmp_path, object_axis=True)
    win = MainWindow(path)
    brama = None
    try:
        tasks = _okno_po_montazu(win)
        assert tasks.tasks.currentRow() < 0
        brama, wszedl, _watki, _glowny = _brama_rachunku(monkeypatch)
        _zapis_drugim_polaczeniem(path)
        win.nav.setFocus(Qt.TabFocusReason)
        win.nav.setCurrentRow(NAV_PORZADKI)
        assert wszedl.wait(_BEZPIECZNIK_LICZNIKOW_S) and not _lista_czynna(win)
        _enter_z_petli(win.nav)
        pierwszy = next(r for r, (_k, _l, akcja) in enumerate(tm._TASKS) if akcja is not None)
        assert tasks.tasks.hasFocus() and tasks.tasks.currentRow() == pierwszy, tasks.tasks.currentRow()
        _enter_z_petli(tasks.tasks)
        assert tasks.pages.currentIndex() == tm._PAGE_LIST
        brama.set()
        _czekaj_na(lambda: _po_wyniku(tasks) and _lista_czynna(win), "rachunek wejścia nie przyłożony")
        _pompuj()
        assert tasks.pages.currentIndex() == tm._TASKS[pierwszy][2] and bledy == [], (tasks.pages.currentIndex(), bledy)
    finally:
        if brama is not None:
            brama.set()
        win.close()


def test_odlozony_klik_ustawia_biezacy_wiersz_dla_powrotu(qapp, tmp_path, monkeypatch):
    """Klik myszą w wiersz WYGASZONY (lista nieaktualna) czeka na wynik i otwiera podstronę - a „← Porządki” wraca na
    TEN wiersz: Qt nie ustawia bieżącego przy kliku w element bez `ItemIsEnabled`, więc dawniej powrót trafiał na wiersz
    sprzed kliku. Mutant: odłożenie bez ustawienia bieżącego wiersza."""
    from horreum.gui import tasks as tm
    _w_tle(monkeypatch)
    path = _seeded_db(tmp_path, object_axis=True)
    win = MainWindow(path)
    brama = None
    try:
        tasks = _okno_po_montazu(win)
        _klik_nav(win, NAV_PORZADKI)
        _czekaj_na(lambda: tasks._liczniki_thread is None and _lista_czynna(win), "lista czynna")
        tasks.tasks.setCurrentItem(_task_item(win, "dup_frames"))
        _klik_nav(win, NAV_DOM)
        brama, wszedl, _watki, _glowny = _brama_rachunku(monkeypatch)
        _zapis_drugim_polaczeniem(path)
        _klik_nav(win, NAV_PORZADKI)
        assert wszedl.wait(_BEZPIECZNIK_LICZNIKOW_S)
        wiersz = _task_item(win, "telescopes_unlabeled")
        QTest.mouseClick(tasks.tasks.viewport(), Qt.LeftButton, Qt.NoModifier,
                         tasks.tasks.visualItemRect(wiersz).center())
        _pompuj()
        assert tasks.pages.currentIndex() == tm._PAGE_LIST, "klik w wiersz wygaszony nie czeka"
        brama.set()
        _czekaj_na(lambda: _po_wyniku(tasks) and tasks.pages.currentIndex() == tm._PAGE_TELESCOPE,
                   "klik odłożony nie otworzył podstrony")
        _wstecz(tasks).click()
        _pompuj()
        assert tasks.tasks.currentItem() is wiersz and tasks.tasks.hasFocus(), tasks.tasks.currentRow()
    finally:
        if brama is not None:
            brama.set()
        win.close()


def test_powrot_oddaje_fokus_liscie_niezaleznie_od_lancucha_fokusu(qapp, tmp_path, monkeypatch):
    """„← Porządki” kładzie fokus na liście na wierszu, z którego człowiek wszedł - także gdy fokus stał gdzie indziej
    (dotąd listę ratował łańcuch fokusu po schowaniu przycisku powrotu). Mutant: `_on_back` bez `setFocus`."""
    _w_tle(monkeypatch)
    win = MainWindow(_seeded_db(tmp_path, object_axis=True))
    try:
        tasks = _okno_po_montazu(win)
        _klik_nav(win, NAV_PORZADKI)
        _czekaj_na(lambda: tasks._liczniki_thread is None and _lista_czynna(win), "lista czynna")
        wiersz = _task_item(win, "telescopes_unlabeled")
        QTest.mouseClick(tasks.tasks.viewport(), Qt.LeftButton, Qt.NoModifier,
                         tasks.tasks.visualItemRect(wiersz).center())
        _pompuj()
        win.nav.setFocus(Qt.OtherFocusReason)
        _wstecz(tasks).click()
        _pompuj()
        assert tasks.tasks.hasFocus() and tasks.tasks.currentItem() is wiersz, QApplication.focusWidget()
    finally:
        win.close()


# ═════════════════════════ AR-379 - jeden rachunek „?”, jedna migawka wejścia w Dostawę

def _licznik_rachunkow(monkeypatch):
    """Rachunki kopii czekających (`_sync_copy_facts` bez podanego wyniku) - podmiana na KLASIE, przed budową strony;
    metoda nie jest slotem (wyłącznie wołania wprost)."""
    from horreum.gui.pipeline import PipelineView
    licznik = []
    prawdziwa = PipelineView._sync_copy_facts

    def _licz(self, czeka=None, **kw):
        if czeka is None:
            licznik.append(1)
        return prawdziwa(self, czeka, **kw)
    monkeypatch.setattr(PipelineView, "_sync_copy_facts", _licz)
    return licznik


def test_gest_pytajnika_liczy_raz_przy_dostawie_zbudowanej_i_niezbudowanej(qapp, tmp_path, monkeypatch):
    """Gest „?” (prawdziwe kliki: sidebar „Porządki”, wiersz „?”) liczył kopie czekające 3 razy przy niezbudowanej
    Dostawie (budowa, powód, pokazanie) i 2 razy przy zbudowanej - teraz RAZ w obu drogach, a linia powodu stoi
    z liczbami.
    Mutanty: `show_reason` zawsze liczy; `showEvent` bez świeżego rachunku; rachunek świeży na zawsze."""
    from test_gui_pipeline import _kopie_bez_faktow
    monkeypatch.setattr(MainWindow, "_pola_poza_watkiem", False)
    sciezka, _kat = _kopie_bez_faktow(tmp_path)
    licznik = _licznik_rachunkow(monkeypatch)
    win = MainWindow(sciezka)
    try:
        win.resize(1500, 900)
        win.show()
        _pompuj()
        for droga in ("niezbudowana", "zbudowana"):
            _klik_nav(win, NAV_PORZADKI)
            tv = win.tasks_view
            klucz = sorted(tv._niewiadome)[0]
            przed = len(licznik)
            QTest.mouseClick(tv.tasks.viewport(), Qt.LeftButton, Qt.NoModifier,
                             tv.tasks.visualItemRect(_task_item(win, klucz)).center())
            _pompuj()
            assert win.stack.currentIndex() == STRONA_DOSTAWA, droga
            assert len(licznik) - przed == 1, (droga, len(licznik) - przed)
            pv = win._strony["pipeline_view"]
            assert pv.lbl_reason.isVisible() and pv.lbl_reason.text(), droga
            _klik_nav(win, NAV_DOM)
    finally:
        win.close()


def test_wejscie_w_dostawe_jedna_migawka_trzech_odczytow(qapp, tmp_path, monkeypatch):
    """Pokazanie Dostawy czyta kopie czekające, liczniki stosów i obrazy „czeka na Ciebie” na JEDNYM połączeniu w jednej
    transakcji (dawniej trzy połączenia, każde w autocommit); rachunek z własnym połączeniem (`_sync_copy_facts` wprost)
    też w transakcji. Mutanty: `showEvent` bez `BEGIN`; synchronizacje bez połączenia wejścia; `_odczyt_bazy` bez
    `BEGIN`."""
    from horreum import scan
    from horreum.gui.pipeline import PipelineView
    from test_gui_pipeline import _kopie_bez_faktow
    sciezka, _kat = _kopie_bez_faktow(tmp_path)
    odczyty = []

    def _szpieg(nazwa, prawdziwa):
        def _f(con, *a, **k):
            odczyty.append((nazwa, id(con), con.in_transaction))
            return prawdziwa(con, *a, **k)
        return _f
    monkeypatch.setattr(scan, "copy_facts_waiting", _szpieg("fakty", scan.copy_facts_waiting))
    monkeypatch.setattr(queries, "stack_lineage_counts", _szpieg("stosy", queries.stack_lineage_counts))
    monkeypatch.setattr(queries, "lineage_pending_frame_ids", _szpieg("rodowod", queries.lineage_pending_frame_ids))
    view = PipelineView(sciezka)
    try:
        view._czeka_rodowod = 1                        # „czeka na Ciebie” czyta stan tylko z członem w logu
        _pompuj()                                      # rachunek konstruktora przestaje być świeży
        odczyty.clear()
        view.show()
        _pompuj()
        assert [n for n, _i, _t in odczyty] == ["fakty", "stosy", "rodowod"], odczyty
        assert len({i for _n, i, _t in odczyty}) == 1 and all(t for _n, _i, t in odczyty), odczyty
        odczyty.clear()
        view._sync_copy_facts()
        assert [(n, t) for n, _i, t in odczyty] == [("fakty", True)], odczyty
    finally:
        view.close()


def test_rachunek_swiezy_tylko_do_konca_obrotu_petli(qapp, tmp_path, monkeypatch):
    """Strona Dostawy zbudowana BEZ pokazania (etap z gestu rodowodu) i pokazana później liczy od nowa - rachunek
    konstruktora jest świeży wyłącznie w obrocie pętli, w którym padł. Mutant: rachunek świeży na zawsze."""
    from horreum.gui.pipeline import PipelineView
    from test_gui_pipeline import _kopie_bez_faktow
    sciezka, _kat = _kopie_bez_faktow(tmp_path)
    licznik = _licznik_rachunkow(monkeypatch)
    view = PipelineView(sciezka)
    try:
        assert len(licznik) == 1
        _pompuj()
        view.show()
        _pompuj()
        assert len(licznik) == 2
    finally:
        view.close()


# ═════════════════════════ AR-380 - tryb od montażu, bieg wyprzedzony, lista nieaktualna bez rachunku

def test_bieg_wyprzedzony_nie_zostawia_listy_wygaszonej(qapp, tmp_path, monkeypatch):
    """Bieg w tle za bramą, w trakcie rachunek synchroniczny (porażka - generacja w górę): wejście w Porządki czekało na
    bieg, którego wynik idzie do kosza - lista zostawała wygaszona bez fazy i bez błędu, także przy następnym wejściu
    (skrót „bez zmian”). Teraz obie wizyty kończą listą czynną. Mutanty: gałąź „bieg w drodze” bez generacji (pierwsze
    wejście); skrót bez warunku listy nieaktualnej (drugie wejście)."""
    _w_tle(monkeypatch)
    path = _seeded_db(tmp_path, object_axis=True)
    win = MainWindow(path)
    smieci = tmp_path / "smieci.db"
    smieci.write_bytes(b"to nie jest baza" * 512)
    zla = sqlite3.connect(str(smieci))
    brama = None
    try:
        tasks = _okno_po_montazu(win)
        prawdziwe = tasks.con
        brama, wszedl, _watki, _glowny = _brama_rachunku(monkeypatch)
        tasks.refresh_counts(w_tle=True)
        assert wszedl.wait(_BEZPIECZNIK_LICZNIKOW_S)
        tasks.con = zla
        tasks.refresh_counts()                            # porażka synchroniczna - generacja w górę
        tasks.con = prawdziwe
        _klik_nav(win, NAV_PORZADKI)
        brama.set()
        _czekaj_na(lambda: tasks._liczniki_thread is None, "bieg")
        _pompuj()
        pierwsze = _lista_czynna(win)
        _klik_nav(win, NAV_DOM)
        _klik_nav(win, NAV_PORZADKI)
        _czekaj_na(lambda: tasks._liczniki_thread is None, "drugie wejście")
        _pompuj()
        assert (pierwsze, _lista_czynna(win)) == (True, True)
    finally:
        if brama is not None:
            brama.set()
        win.close()
        zla.close()


def test_lista_nieaktualna_bez_biegu_wraca_przy_wejsciu(qapp, tmp_path, monkeypatch):
    """Lista nieaktualna bez rachunku w drodze (stan utknięcia - dawniej osiągalny biegiem wyprzedzonym) przy
    niezmienionym odcisku bazy: wejście liczy, zamiast wyjść skrótem „bez zmian” z listą wygaszoną do zmiany bazy.
    Mutant: skrót bez `not _nieaktualny`."""
    _w_tle(monkeypatch)
    bledy = _bledy_haka(monkeypatch)
    win = MainWindow(_seeded_db(tmp_path, object_axis=True))
    try:
        tasks = _okno_po_montazu(win)
        tasks._wygas_wiersze()                           # utknięcie: lista nieaktualna, żadnego biegu
        assert tasks._liczniki_thread is None and tasks._nieaktualny
        _klik_nav(win, NAV_PORZADKI)
        _czekaj_na(lambda: tasks._liczniki_thread is None and _lista_czynna(win), "lista po wejściu")
        assert bledy == [], bledy
    finally:
        win.close()


def test_powrot_przed_pierwszym_wejsciem_liczy_trybem_widoku(qapp, tmp_path, monkeypatch):
    """Tryb liczników zna widok od montażu (`TasksView(w_tle=True)`): powrót z podstrony ZANIM gospodarz choć raz wszedł
    w Porządki liczy po zapisie w tle (dawniej tryb zapamiętywało dopiero wejście - powrót liczył na wątku GUI).
    Mutant: tryb z konstruktora pominięty w drodze wejścia."""
    path = _seeded_db(tmp_path, object_axis=True)
    con = db.open_db(path)
    tv = _widok(con, w_tle=True)
    brama = None
    try:
        _klik_w(tv, _wiersz(tv, "telescopes_unlabeled"))
        assert tv.pages.currentIndex() == tasks_mod._PAGE_TELESCOPE
        _zapis_drugim_polaczeniem(path)
        brama, wszedl, watki, glowny = _brama_rachunku(monkeypatch)
        QTest.mouseClick(_wstecz(tv), Qt.LeftButton)
        _pompuj()
        assert wszedl.wait(_BEZPIECZNIK_LICZNIKOW_S), "powrót nie liczył w tle"
        assert glowny not in watki
        brama.set()
        _czekaj_na(lambda: tv._liczniki_thread is None and tv._odcisk_licznikow == queries.odcisk_bazy(con),
                   "rachunek powrotu")
    finally:
        if brama is not None:
            brama.set()
        tv.zatrzymaj_pola()
        tv.close()
        con.close()


def test_inwariant_listy_nieaktualnej_przy_koncu_biegu(qapp, tmp_path, monkeypatch):
    """EXPECT: lista nieaktualna bez rachunku bieżącej generacji w drodze i bez zamówienia to błąd programu - pomocnik
    rzuca, a koniec biegu (`_sprzataj_liczniki`) go woła: bieg, którego wynik idzie do kosza (generacja w górę z
    porzuceniem listy), kończy się `AssertionError`, nie cichą listą wygaszoną. Mutanty: pusty inwariant; bez wołania
    w `_sprzataj_liczniki`. Slot końca wątku (`QThread.finished`, kolejka między wątkami) oddaje wyjątek hakowi
    `sys.excepthook` (zmierzone, PySide6 6.9.2) - test go podmienia i czyta."""
    import sys
    bledy = []
    monkeypatch.setattr(sys, "excepthook", lambda typ, exc, tb: bledy.append(exc))
    path = _seeded_db(tmp_path, object_axis=True)
    con = db.open_db(path)
    tv = _widok(con, w_tle=True)
    brama = None
    try:
        tv._nieaktualny = True
        with pytest.raises(AssertionError):
            tv._inwariant_listy_nieaktualnej()
        tv._nieaktualny = False
        brama, wszedl, _watki, _glowny = _brama_rachunku(monkeypatch)
        tv.refresh_counts(w_tle=True)
        assert wszedl.wait(_BEZPIECZNIK_LICZNIKOW_S)
        tv._wygas_wiersze()
        tv._liczniki_gen += 1                           # droga, która porzuca listę: wynik biegu pójdzie do kosza
        brama.set()
        _czekaj_na(lambda: tv._liczniki_thread is None, "koniec biegu")
        _pompuj()
        assert [type(b) for b in bledy] == [AssertionError] and "nieaktualna" in str(bledy[0]), bledy
        # Inwariant pada PO końcu serii: faza zgaszona i sygnał gospodarza poszedł, zanim asercja przerwała slot.
        assert not tv.liczy_w_tle() and tv.faza_licznikow.isHidden()
    finally:
        if brama is not None:
            brama.set()
        tv._nieaktualny = False
        _czekaj_na(lambda: tv._liczniki_thread is None, "sprzątnięcie")
        tv.zatrzymaj_pola()
        tv.close()
        con.close()
