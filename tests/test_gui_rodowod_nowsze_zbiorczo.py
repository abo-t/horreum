"""Odrzucenie wejść nowszych niż obraz jednym gestem, cofnięcie bez odsłaniania, panel przy wejściu
(AR-178) - testy sterujące realnym oknem Qt (offscreen).

Do AR-178 przycisk „Odrzuć nowsze niż obraz" działał na jeden stos (9 stosów NGC7635 = 9 gestów:
wiersz Porządków → zaznaczenie obrazu → panel „Rodowód" → przycisk), a cofnięcie wymagało
odsłonięcia stosu w „Przeglądzie". Gesty idą prawdziwym zdarzeniem: klik myszą w wiersz Porządków,
przycisk i pozycję menu, zdarzenie menu kontekstowego na viewporcie tabeli (droga prawego kliku)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, QEvent, QThread, Qt
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from horreum import db
from horreum.gui import grid as grid_mod, grid_model, i18n, queries
from test_gui_rodowod_tabela import (NOW, _klik, _klik_wiersza_zadania, _seed, _seed_nowsze,
                                     _stos_nowszy, _zaznacz, _zaznaczone)


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


def _seed_dwa(con):
    """`_seed` + stos 60 (`_seed_nowsze`: 62 - ręka, noc obrazu; 63, 64 - ręka po zapisie; 66 - ręka
    po zapisie, już odrzucone) + stos 70 z SAMYMI wejściami ręki po zapisie (72, 73) - po geście
    zostanie bez wejść, jak `…_mono_WBPP` Ha i SII na kopii archiwum."""
    _seed(con)
    _seed_nowsze(con)
    _stos_nowszy(con, 70, 71, ct="2023-04-22T09:00:00Z", wejscia=[
        (72, "2023-04-22T21:00:00", "fits", 0), (73, "2023-04-23T21:00:00", "fits", 0)])
    con.execute("INSERT INTO location (frame_id, volume, path, present) "
                "VALUES (70, 'V', '/a/S/stos70.xisf', 1)")
    con.commit()


@pytest.fixture
def con(tmp_path):
    c = db.open_db(str(tmp_path / "n.db"))
    _seed_dwa(c)
    yield c
    c.close()


@pytest.fixture
def strona(qapp, con):
    from horreum.gui.flows.znajdz_view import ZnajdzView
    v = grid_mod.FramesView(con, now_fn=lambda: NOW)
    v._writeback_async = False
    s = ZnajdzView(v)
    s.resize(1400, 900)
    s.show()
    yield s
    if not any(t.isRunning() for t in v.findChildren(QThread)):
        s.close()
        s.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


@pytest.fixture
def okno(qapp, tmp_path, monkeypatch):
    """`MainWindow` nad tą samą bazą, bez wątków tła (wzór `test_gui_rodowod_tabela`)."""
    from horreum.gui.app import MainWindow
    monkeypatch.setattr(MainWindow, "_pola_poza_watkiem", False)
    path = str(tmp_path / "okno.db")
    c = db.open_db(path)
    _seed_dwa(c)
    c.close()
    win = MainWindow(path)
    win.show()
    yield win
    win.close()


def _wejdz_z_porzadkow(win):
    from horreum.gui.app import NAV_PORZADKI, STRONA_ZBIORY
    win._show_view(NAV_PORZADKI)
    _klik_wiersza_zadania(win.tasks_view, "lineage_newer")
    assert win._strona() == STRONA_ZBIORY
    return win.grid_view


def _kolejnosc(v):
    return [r["frame_id"] for r in v.model._rows if "_group" not in r]


def _stan(con, fid):
    return tuple(con.execute("SELECT asserted_by, excluded FROM integration_input "
                             "WHERE input_frame_id = ?", (fid,)).fetchone())


def _tabela(con):
    return [tuple(r) for r in con.execute(
        "SELECT integration_id, input_frame_id, asserted_by, excluded FROM integration_input "
        "ORDER BY rowid")]


def _zdarzenia(con, verb):
    return con.execute("SELECT COUNT(*) FROM event WHERE verb = ?", (verb,)).fetchone()[0]


def _menu_na_wierszu(v, fid):
    """Zdarzenie menu kontekstowego na wierszu klatki `fid` - droga prawego kliku
    (`customContextMenuRequested`, wzór `test_gui_lead_copy._prawy_klik`)."""
    QApplication.processEvents()
    wiersz = next(i for i, r in enumerate(v.model._rows) if r.get("frame_id") == fid)
    rect = v.table.visualRect(v.model.index(wiersz, 0))
    vp = v.table.viewport()
    QApplication.sendEvent(vp, QContextMenuEvent(QContextMenuEvent.Mouse, rect.center(),
                                                 vp.mapToGlobal(rect.center())))
    QApplication.processEvents()


def _klik_pozycji_menu(v, akcja):
    menu = v._menu_tabeli
    assert menu.isVisible() and akcja.isVisible()
    QTest.mouseClick(menu, Qt.LeftButton, Qt.NoModifier, menu.actionGeometry(akcja).center())
    QApplication.processEvents()


def test_gest_zbiorczy_z_menu_perspektywy_odrzuca_wszystkie_stosy(strona, con):
    """Prawy klik na JEDNYM obrazie perspektywy → „Odrzuć nowsze niż obraz we wszystkich obrazach":
    odrzucone są wejścia do odrzucenia OBU obrazów (cel = widok, nie zaznaczenie), reszta
    nietknięta; zdanie mówi liczby i obraz, który został bez wejść; perspektywa pustoszeje (stan),
    a recepta ma jeden wykonalny człon „Cofnij werdykt". Falsyfikatory: cel z zaznaczenia (stos 70
    nietknięty); zdanie bez członu „bez wejść"."""
    v = strona.frames_view
    zdania, recepty = [], []
    v.status_message.connect(zdania.append)
    v.status_recipe.connect(recepty.append)
    v.apply_perspective(grid_model.PRESET_LINEAGE_NEWER)
    assert sorted(v._frame_ids) == [60, 70]
    _menu_na_wierszu(v, 60)
    assert v.act_reject_newer_all.isEnabled()
    assert v.act_reject_newer_all.toolTip() == i18n.t_plural(
        "grid.lin.reject_newer_all_tip", 2, undo=i18n.t("grid.lin.undo"))
    _klik_pozycji_menu(v, v.act_reject_newer_all)
    assert [_stan(con, f) for f in (63, 64, 72, 73)] == [("user", 1)] * 4
    assert _stan(con, 62) == ("user", 0) and _stan(con, 66) == ("user", 1)
    assert _zdarzenia(con, "integration.judged") == 4
    assert zdania[-1] == (i18n.t("grid.lin.judged_excluded", n=4)
                          + i18n.t_plural("grid.lin.judged_in_images", 2)
                          + i18n.t_plural("grid.lin.left_without_inputs", 1))
    assert v._frame_ids == [] and queries.lineage_newer_inputs(con) == {}
    assert str(recepty[-1]) == i18n.t("grid.lin.undo")
    assert len(recepty[-1].czlony) == 1 and recepty[-1].czlony[0].wykonaj is not None


def test_cofnij_zbiorczy_jednym_kliknieciem_bez_odslaniania(okno):
    """Droga z Domu: wiersz Porządków → menu → gest zbiorczy, potem klik w receptę paska: tabela
    `integration_input` wraca do stanu sprzed gestu jednym kliknięciem, bez odsłaniania, a oba
    obrazy wracają do perspektywy zaznaczone. Falsyfikator: `bez_widoku=False` w `_ODWROT_WERDYKTU`
    (człon cofnięcia bez wykonawcy - przycisk wygaszony, tabela niecofnięta)."""
    win = okno
    g = _wejdz_z_porzadkow(win)
    przed = _tabela(win.con)
    _menu_na_wierszu(g, _kolejnosc(g)[0])
    _klik_pozycji_menu(g, g.act_reject_newer_all)
    assert g._frame_ids == []
    assert win.recipe_label.isVisible() and win.recipe_label.isEnabled()
    QTest.mouseClick(win.recipe_label, Qt.LeftButton)
    QApplication.processEvents()
    assert _tabela(win.con) == przed
    assert sorted(g._frame_ids) == [60, 70] and _zaznaczone(g) == [60, 70]
    assert _zdarzenia(win.con, "integration.judgment_restored") == 4


def test_wejscie_z_porzadkow_otwiera_panel_i_zaznacza_pierwszy_obraz(okno):
    """Klik myszą w wiersz Porządków: Zbiory z perspektywą, pierwszy obraz tabeli zaznaczony, panel
    „Rodowód" otwarty na nim z przyciskiem gestu, recepta mówi, gdzie gest na wszystkie naraz.
    Falsyfikator: bez `_wejdz_w_nowsze` w `_po_perspektywie` (panel zamknięty, zaznaczenie puste)."""
    win = okno
    recepty = []
    win.grid_view.status_recipe.connect(recepty.append)
    g = _wejdz_z_porzadkow(win)
    pierwszy = _kolejnosc(g)[0]
    assert _zaznaczone(g) == [pierwszy]
    assert g._lineage_panel_open() and g._lineage_frame_id == pierwszy
    assert g.lineage_bar.btn_reject_newer.isVisible()
    assert str(recepty[-1]) == i18n.t(
        "grid.lin.newer_recipe", reject=i18n.t("grid.lin.reject_newer"),
        panel=i18n.t("grid.sel.lineage"), all=i18n.t("grid.lin.reject_newer_all"))


def test_wejscie_nie_zdejmuje_podgladu_makra(strona):
    """Podgląd makra stoi (panel makra zamknięty - podgląd zostaje): wejście w perspektywę zaznacza
    pierwszy obraz, ale panelu rodowodu nie otwiera - otwarcie zdjęłoby cudzy podgląd. Falsyfikator:
    otwieranie panelu bez warunku na podgląd (`_toggle_panel` zdejmuje podgląd makra)."""
    v = strona.frames_view
    v.refresh()
    _klik(v.sel_bar.btn_macro)
    v.macro_bar.asg_kw.setCurrentText("TELESCOP")
    v.macro_bar.asg_expr.setText("EQ6")
    _klik(v.macro_bar.btn_prev)
    _klik(v.sel_bar.btn_macro)                                  # zamknięcie: podgląd zostaje
    assert v.model._preview_active() and v.panel_stack.isHidden()
    v.apply_perspective(grid_model.PRESET_LINEAGE_NEWER)
    assert v.model._preview_active() and not v._lineage_panel_open()
    assert _zaznaczone(v) == [_kolejnosc(v)[0]]


def test_po_gescie_z_panelu_cel_przechodzi_na_nastepny_a_cofniecie_wraca_bez_odslaniania(strona,
                                                                                          con):
    """Przycisk panelu na pierwszym obrazie perspektywy: obraz wypada (stan), zaznaczenie i panel
    przechodzą na następny - gest na nim jest o klik bliżej. Recepta: jeden wykonalny człon; jego
    wykonanie przywraca obraz do perspektywy i do zaznaczenia (nie zostaje na „następnym").
    Falsyfikator: bez `nastepne` w `_panel_po_werdykcie` (zaznaczenie puste po geście)."""
    v = strona.frames_view
    recepty = []
    v.status_recipe.connect(recepty.append)
    v.apply_perspective(grid_model.PRESET_LINEAGE_NEWER)
    pierwszy, drugi = _kolejnosc(v)
    assert _zaznaczone(v) == [pierwszy] and v._lineage_panel_open()
    _klik(v.lineage_bar.btn_reject_newer)
    assert v._frame_ids == [drugi]
    assert _zaznaczone(v) == [drugi] and v._lineage_frame_id == drugi
    assert v.lineage_bar.btn_reject_newer.isVisible()
    assert len(recepty[-1].czlony) == 1 and recepty[-1].czlony[0].wykonaj is not None
    recepty[-1].czlony[0].wykonaj()
    QApplication.processEvents()
    assert sorted(v._frame_ids) == [60, 70] and _zaznaczone(v) == [pierwszy]


def test_przycisk_jednego_stosu_mowi_o_obrazie_bez_wejsc(strona):
    """Zdanie przycisku panelu: obraz z wejściem sprzed zapisu (60) - samo „Odrzucono 2"; obraz
    z samymi nowszymi (70) - człon „1 obraz został bez wejść" (ten sam, co gest zbiorczy).
    Falsyfikator: człon bez warunku na stan po zapisie (stoi także przy 60)."""
    v = strona.frames_view
    zdania = []
    v.status_message.connect(zdania.append)
    v.refresh()
    if not v._lineage_panel_open():
        _klik(v.sel_bar.btn_lineage)
    _zaznacz(v, [60])
    _klik(v.lineage_bar.btn_reject_newer)
    assert zdania[-1] == i18n.t("grid.lin.judged_excluded", n=2)
    _zaznacz(v, [70])
    _klik(v.lineage_bar.btn_reject_newer)
    assert zdania[-1] == (i18n.t("grid.lin.judged_excluded", n=2)
                          + i18n.t_plural("grid.lin.left_without_inputs", 1))


def test_menu_nowszych_milczy_poza_perspektywa_i_gasnie_w_zajetosci(strona, con):
    """Poza perspektywą prawy klik na zwykłym obrazie menu nie pokazuje (żadna sekcja nie pasuje).
    W perspektywie, przy etapie Dostawy w biegu, pozycja stoi wygaszona z powodem, a slot odmawia bez
    zapisu (druga linia obrony). Falsyfikator: widoczność pozycji bez flagi perspektywy."""
    v = strona.frames_view
    v.apply_perspective(grid_model._PRESET_CZYSTY)
    _menu_na_wierszu(v, 60)
    assert not v._menu_tabeli.isVisible()
    v.apply_perspective(grid_model.PRESET_LINEAGE_NEWER)
    v.set_busy(True)
    try:
        _menu_na_wierszu(v, 60)
        assert v.act_reject_newer_all.isVisible() and not v.act_reject_newer_all.isEnabled()
        assert v.act_reject_newer_all.toolTip() == i18n.t("grid.inplace.busy_stage")
        v._menu_tabeli.hide()
        v._on_reject_newer_all()
        assert _zdarzenia(con, "integration.judged") == 0
    finally:
        v.set_busy(False)


@pytest.mark.parametrize("n, w_obrazach, bez_wejsc", [
    (1, " w 1 obrazie", " · 1 obraz został bez wejść"),
    (2, " w 2 obrazach", " · 2 obrazy zostały bez wejść"),
    (5, " w 5 obrazach", " · 5 obrazów zostało bez wejść"),
    (12, " w 12 obrazach", " · 12 obrazów zostało bez wejść"),
    (22, " w 22 obrazach", " · 22 obrazy zostały bez wejść")])
def test_zdania_gestu_zbiorczego_sie_odmieniaja(n, w_obrazach, bez_wejsc):
    """Liczebnik i czasownik w zgodzie (1, 2, 5, 12, 22), podpowiedź pozycji menu w miejscowniku."""
    assert i18n.t_plural("grid.lin.judged_in_images", n) == w_obrazach
    assert i18n.t_plural("grid.lin.left_without_inputs", n) == bez_wejsc
    assert i18n.t_plural("grid.lin.reject_newer_all_tip", n, undo="x").startswith(
        f"W {n} obrazie " if n == 1 else f"W {n} obrazach ")


@pytest.mark.parametrize("n, w_obrazach, bez_wejsc", [
    (1, " in 1 image", " · 1 image was left without inputs"),
    (2, " in 2 images", " · 2 images were left without inputs"),
    (22, " in 22 images", " · 22 images were left without inputs")])
def test_zdania_gestu_zbiorczego_EN(n, w_obrazach, bez_wejsc):
    i18n.set_lang("en")
    assert i18n.t_plural("grid.lin.judged_in_images", n) == w_obrazach
    assert i18n.t_plural("grid.lin.left_without_inputs", n) == bez_wejsc


# ---------- cofnięcie: najnowszy gest w jednym oknie, ponowienie po błędzie bazy ----------

def test_odrzuc_potwierdz_odrzuc_cofniecie_dotyczy_ostatniego_gestu(strona, con):
    """Sekwencja w JEDNYM oknie, klikami w panelu: odrzuć wejście 1 (przed gestem: okno czasu),
    potwierdź je, odrzuć znowu - „Cofnij werdykt” cofa OSTATNI gest (wraca potwierdzenie ręki), nie
    pierwszy (powrót do okna czasu nadpisałby późniejszą decyzję). Każdy werdykt podmienia migawkę
    i receptę, więc cofnięcie gestu sprzed nowszego werdyktu nie jest z tego okna osiągalne.
    Falsyfikator: migawka werdyktu, która nie schodzi przy nowszym geście."""
    from test_gui_rodowod_tabela import _klik_wiersza
    v = strona.frames_view
    recepty = []
    v.status_recipe.connect(recepty.append)
    v.refresh()
    if not v._lineage_panel_open():
        _klik(v.sel_bar.btn_lineage)
    _zaznacz(v, [10])
    bar = v.lineage_bar
    assert _stan(con, 1) == ("window", 0)
    for przycisk, po in ((bar.btn_reject, ("user", 1)), (bar.btn_confirm, ("user", 0)),
                         (bar.btn_reject, ("user", 1))):
        _klik_wiersza(bar.items, 1)
        _klik(przycisk)
        assert _stan(con, 1) == po
    assert [z.before for z in v._migawka_werdyktu[0][2]] == [("user", 0)]
    recepty[-1].czlony[0].wykonaj()
    QApplication.processEvents()
    assert _stan(con, 1) == ("user", 0)


def test_cofniecie_po_bledzie_bazy_zostawia_recepte_i_daje_sie_ponowic(strona, con, monkeypatch):
    """Błąd bazy przy drugim przywróceniu: transakcja cofnięcia wycofana w całości, zdanie mówi, że
    nic się nie zmieniło, a recepta zostaje - drugi klik w nią (po ustąpieniu błędu) cofa gest.
    Falsyfikator: migawka zdejmowana PRZED zapisem (drugi klik: „nie ma czego cofać”)."""
    import sqlite3
    from horreum import repo
    v = strona.frames_view
    zdania, recepty = [], []
    v.status_message.connect(zdania.append)
    v.status_recipe.connect(recepty.append)
    przed = _tabela(con)
    v.apply_perspective(grid_model.PRESET_LINEAGE_NEWER)
    _klik(v.lineage_bar.btn_reject_newer)
    po_gescie = _tabela(con)
    assert po_gescie != przed
    prawdziwa = repo.emit_event
    licznik = {"n": 0}

    def _pada(con_, **kw):
        if kw.get("verb") == "integration.judgment_restored":
            licznik["n"] += 1
            if licznik["n"] == 2:
                raise sqlite3.OperationalError("database is locked")
        return prawdziwa(con_, **kw)
    monkeypatch.setattr(repo, "emit_event", _pada)
    recepty[-1].czlony[0].wykonaj()
    QApplication.processEvents()
    assert _tabela(con) == po_gescie
    assert zdania[-1] == i18n.t("grid.lin.undo_failed", undo=i18n.t("grid.lin.undo"))
    assert str(recepty[-1]) == i18n.t("grid.lin.undo") and recepty[-1].czlony[0].wykonaj is not None
    monkeypatch.setattr(repo, "emit_event", prawdziwa)
    recepty[-1].czlony[0].wykonaj()
    QApplication.processEvents()
    assert _tabela(con) == przed
