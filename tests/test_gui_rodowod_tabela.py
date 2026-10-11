"""Rodowód w tabeli Zbiorów - testy STERUJĄCE realnym oknem Qt (offscreen).

Dwuklik w panelu rodowodu prowadzi do klatek w Zbiorach (obie osie panelu, jeden handler), a chip
zbioru niesie drogę powrotu. Kolumna, facet i preset „Gotowe obrazy" czytają jeden read-model stanu
rodowodu (`queries.stack_lineage_states`); „Cofnij" po werdykcie wraca do stanu sprzed gestu; lista
wejść pokazuje wspólny katalog raz; memo Dostawy liczy stosy ze stanu. Gesty idą prawdziwym
zdarzeniem myszy na wierszu listy albo przycisku, nie emisją sygnału - inaczej test przechodziłby
przy odpiętym `itemDoubleClicked`/`clicked`."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, QEvent, QThread, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from horreum import db, filter_engine
from horreum.gui import grid as grid_mod, grid_model, i18n, queries

NOW = "2026-10-11T12:00:00"


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


def _seed(con):
    """Stos 10 (`masterLight.xisf`) z dwoma wejściami (1, 2), light 3 spoza stosu, master flat 4."""
    con.executemany(
        "INSERT INTO frame (id, sha1_data, kind, filetype, first_seen_at) VALUES (?,?,?,?,?)",
        [(1, "d1", "light", "fits", NOW), (2, "d2", "light", "fits", NOW),
         (3, "d3", "light", "fits", NOW), (4, "d4", "master_flat", "xisf", NOW),
         (10, "m10", "master_light", "xisf", NOW)])
    con.executemany(
        "INSERT INTO header (frame_id, raw_json, date_obs, exptime) VALUES (?,?,?,?)",
        [(1, "{}", "2026-08-08T22:00:00", 300.0), (2, "{}", "2026-08-08T23:00:00", 300.0),
         (3, "{}", "2026-08-09T22:00:00", 300.0), (10, "{}", None, None)])
    con.executemany(
        "INSERT INTO location (frame_id, volume, path, present) VALUES (?,?,?,?)",
        [(1, "V", "/a/L/l1.fits", 1), (2, "V", "/a/L/l2.fits", 1), (3, "V", "/a/L/l3.fits", 1),
         (4, "V", "/a/C/mf4.xisf", 1), (10, "V", "/a/S/masterLight.xisf", 1)])
    con.execute("INSERT INTO integration (id, master_frame_id, created_at, degenerate, ambiguous, "
                "telescope_mismatch) VALUES (5, 10, ?, 0, 0, 0)", (NOW,))
    con.executemany("INSERT INTO integration_input (integration_id, input_frame_id, asserted_by) "
                    "VALUES (5, ?, 'window')", [(1,), (2,)])
    con.commit()


@pytest.fixture
def con(tmp_path):
    c = db.open_db(str(tmp_path / "r.db"))
    _seed(c)
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


def _zaznacz(v, ids):
    v.table.clearSelection()
    v._przywroc_zaznaczenie(ids)
    v._date_timer.stop()
    v._refresh_lineage()


def _zaznaczone(v):
    return sorted(r["frame_id"] for r in v._selected_data_rows())


def _dwuklik(lista, wiersz):
    """Prawdziwy dwuklik myszą w środek wiersza listy. Sekwencja jak u człowieka: pierwsze
    wciśnięcie (`mouseClick`), potem drugie jako `DblClick` - widok elementów Qt 6 uznaje dwuklik
    tylko na indeksie, który dostał wcześniej wciśnięcie; samo `mouseDClick` go nie niesie."""
    QApplication.processEvents()
    rect = lista.visualItemRect(lista.item(wiersz))
    assert rect.isValid() and lista.viewport().rect().contains(rect.center()), "wiersz poza kadrem"
    QTest.mouseClick(lista.viewport(), Qt.LeftButton, Qt.NoModifier, rect.center())
    QTest.mouseDClick(lista.viewport(), Qt.LeftButton, Qt.NoModifier, rect.center())
    QApplication.processEvents()


def _chipy(s):
    return [c.text() for c in s._pula if c.isVisible()]


# ---------- seam: dwuklik → klatki w Zbiorach ----------

def test_dwuklik_wejscia_stosu_pokazuje_wejscia_w_Zbiorach_z_klatka_zaznaczona(strona):
    v = strona.frames_view
    _zaznacz(v, [10])
    v._toggle_panel("lineage")
    lista = v.lineage_bar.items
    assert lista.count() == 2
    _dwuklik(lista, 1)                                   # drugi wiersz = klatka 2
    assert sorted(v._frame_ids) == [1, 2]
    assert _zaznaczone(v) == [2]
    etykieta = i18n.t("grid.lin.show.inputs", name="masterLight.xisf", n=2)
    assert _chipy(strona) == [f"{etykieta}  ×"]          # klasyczna: chip jedyną kontrolką składnika
    assert etykieta in v.sel_bar.criteria_label.toolTip()
    assert v.combo_persp.currentData() == ("preset", "Przegląd")
    assert "(zmieniona)" in v.combo_persp.currentText()  # 2 wejścia stosu to nie „Przegląd"


def test_chip_wraca_do_stanu_sprzed_wejscia_ze_stosem_zaznaczonym(strona):
    v = strona.frames_view
    v.apply_perspective("Duplikaty")
    v._on_perspective()
    v.apply_perspective("Przegląd")
    v._facet_state = {"kind": {"in": [["master_light", "master_light"]]}}
    v.refresh()
    _zaznacz(v, [10])
    v._toggle_panel("lineage")
    _dwuklik(v.lineage_bar.items, 0)
    assert sorted(v._frame_ids) == [1, 2] and _zaznaczone(v) == [1]
    assert v._facet_state == {}
    strona._pula[0].click()                              # „×" chipu
    QApplication.processEvents()
    assert sorted(v._frame_ids) == [10]
    assert v._facet_state == {"kind": {"in": [["master_light", "master_light"]]}}
    assert _zaznaczone(v) == [10]
    assert v.lineage_bar.items.count() == 2              # panel znów mówi o stosie
    assert _chipy(strona) == []


def test_wyczysc_zbior_zdejmuje_wskazane_bez_powrotu(strona):
    v = strona.frames_view
    v.show_frames([1, 2], label="X", focus=1)
    assert sorted(v._frame_ids) == [1, 2]
    assert v.sel_bar.btn_clear.isEnabled()              # składnik zawęża - przycisk go zdejmuje
    v._on_clear_selection()
    assert sorted(v._frame_ids) == [1, 2, 3, 4, 10]
    assert v._powrot_wskazanych is None and v._wskazane is None


def test_wejscie_z_wejscia_cofa_o_jeden_krok(strona):
    v = strona.frames_view
    v.show_frames([1, 2, 3], label="A", focus=1)
    v.show_frames([2], label="B", focus=2)
    assert v._frame_ids == [2]
    v.zdejmij_skladnik(("wskazane",))
    assert sorted(v._frame_ids) == [1, 2, 3] and v._wskazane[1] == "A"
    v.zdejmij_skladnik(("wskazane",))
    assert sorted(v._frame_ids) == [1, 2, 3, 4, 10] and v._wskazane is None


def test_show_frames_pusta_lista_to_blad_wolajacego(strona):
    with pytest.raises(ValueError):
        strona.frames_view.show_frames([], label="X")


def test_dwuklik_osi_kalibracji_prowadzi_do_mastera_a_luka_milczy(strona):
    """Oś kalibracji (K1): ten sam handler, `UserRole` = master; wiersz luki nie ma klatki."""
    v = strona.frames_view
    _zaznacz(v, [3])
    v._toggle_panel("lineage")
    v.lineage_bar.set_calibration([
        {"relation": "dark", "master_frame_id": None, "asserted_by": None, "master_path": None,
         "pending": False, "gap": "no_master", "days_apart": None},
        {"relation": "flat", "master_frame_id": 4, "asserted_by": "horreum",
         "master_path": "/a/C/mf4.xisf", "pending": False, "gap": None, "days_apart": 2}])
    emisje = []
    v.lineage_bar.frames_requested.connect(lambda *a: emisje.append(a))
    _dwuklik(v.lineage_bar.items, 0)                     # luka: cisza
    assert emisje == [] and v._wskazane is None
    _dwuklik(v.lineage_bar.items, 1)
    assert emisje == [([4], 4, "calibration")]
    assert v._frame_ids == [4] and _zaznaczone(v) == [4]
    assert _chipy(strona) == [f"{i18n.t('grid.lin.show.calibration', name='l3.fits', n=1)}  ×"]


def test_most_gospodarza_dostaje_wejscie_gdy_wstrzykniety(strona):
    v = strona.frames_view
    wolania = []
    v.show_frames_fn = lambda ids, **kw: wolania.append((ids, kw))
    _zaznacz(v, [10])
    v._toggle_panel("lineage")
    _dwuklik(v.lineage_bar.items, 0)
    assert wolania == [([1, 2], {"label": i18n.t("grid.lin.show.inputs", name="masterLight.xisf",
                                                    n=2), "focus": 1})]
    assert v._wskazane is None                           # widok sam nic nie zrobił


# ---------- R1: read-model stanu, kolumna, facet, preset ----------

def _seed_stany(con):
    """Po jednym gotowym obrazie na każdy stan rodowodu (frame 20..27), wejścia z lightów 1-3."""
    stosy = {20: "window", 21: "mixed", 22: "history", 23: "exact", 24: "pending",
             25: "rejected", 26: "none", 27: "uncounted"}
    for fid in stosy:
        con.execute("INSERT INTO frame (id, sha1_data, kind, filetype, first_seen_at) "
                    "VALUES (?, ?, 'master_light', 'xisf', ?)", (fid, f"s{fid}", NOW))
        con.execute("INSERT INTO location (frame_id, volume, path, present) VALUES (?, 'V', ?, 1)",
                    (fid, f"/a/S/stos{fid}.xisf"))
    for fid in (20, 21, 22, 23, 24, 25, 26):
        powod = "degenerate_window" if fid == 24 else None
        con.execute("INSERT INTO integration (id, master_frame_id, created_at, degenerate, ambiguous, "
                    "telescope_mismatch, unresolved_reason) VALUES (?, ?, ?, 0, 0, 0, ?)",
                    (fid, fid, NOW, powod))
    wejscia = [(20, 1, "window", 0), (20, 2, "window", 0),
               (21, 1, "window", 0), (21, 2, "user", 0),
               (22, 1, "history", 0), (22, 2, "user", 0),
               (23, 1, "harvest", 0), (23, 2, "user", 0),
               (25, 1, "user", 1)]
    con.executemany("INSERT INTO integration_input (integration_id, input_frame_id, asserted_by, "
                    "excluded) VALUES (?, ?, ?, ?)", wejscia)
    con.commit()
    return stosy


def test_read_model_stanu_rodowodu_agregacja_jawna(con):
    """stan z jawnej agregacji, nie z min/max rangi - mieszany, odrzucony, czekający na gest
    i nieliczony to cztery różne zdania. Komplet tokenów = komplet etykiet kolumny."""
    oczekiwane = _seed_stany(con)
    stany = queries.stack_lineage_states(con)
    assert {fid: stany[fid] for fid in oczekiwane} == oczekiwane
    assert stany[10] == "window"                       # stos z `_seed`
    assert 1 not in stany                              # light: n.d.
    assert set(queries.LINEAGE_STATES) == set(grid_model._STANY_RODOWODU) \
        == set(grid_model._TIPY_RODOWODU)
    # liść facetu i jego licznik idą tą samą drogą
    assert filter_engine.run({"facet": "lineage", "value": "pending"},
                             leaf_fn=lambda k, kw, p1, p2: queries.leaf_frame_ids(con, k, kw, p1, p2),
                             universe_fn=lambda: queries.all_frame_ids(con)) == {24}
    assert dict(queries.facet_lineage(con, [1, 10, 20, 24, 27])) == {
        "window": 2, "pending": 1, "uncounted": 1}


def test_liczniki_memo_sa_rozlaczne_i_licza_ze_stanu(con):
    """wszystkie = nieliczone + z wejściami + policzone bez wejść; wycofany stos nie liczy się
    wcale, stos bez kopii - w podpowiedzi."""
    _seed_stany(con)
    con.execute("UPDATE frame SET retired_at = ? WHERE id = 26", (NOW,))
    con.execute("UPDATE location SET present = 0 WHERE frame_id = 27")
    con.commit()
    n = queries.stack_lineage_counts(con)
    # żywe: 10, 20-25, 27 = 8; z wejściami 10,20,21,22,23 = 5; bez wejść 24,25 = 2; nieliczony 27
    assert n == {"all": 8, "uncounted": 1, "with_inputs": 5, "without_inputs": 2, "no_copy": 1}
    assert n["all"] == n["uncounted"] + n["with_inputs"] + n["without_inputs"]


def _tekst_komorki(v, frame_id, klucz, rola=Qt.DisplayRole):
    kol = v.model.base_col(klucz)
    for i, r in enumerate(v.model._rows):
        if isinstance(r, dict) and r.get("frame_id") == frame_id:
            return v.model.data(v.model.index(i, kol), rola)
    raise AssertionError(f"brak wiersza {frame_id}")


def test_preset_gotowe_obrazy_pokazuje_stosy_pogrupowane_po_rodowodzie(strona, con):
    oczekiwane = _seed_stany(con)
    v = strona.frames_view
    v.apply_perspective(grid_mod.PRESET_READY_IMAGES)
    assert sorted(v._frame_ids) == sorted([10, *oczekiwane])
    assert v.combo_group.currentData() == "_rodowod"
    belki = [r["_group"] for r in v.model._rows if "_group" in r]
    assert belki == [i18n.t(grid_model._STANY_RODOWODU[s]) for s in queries.LINEAGE_STATES]
    assert _tekst_komorki(v, 24, "_rodowod") == i18n.t("grid.lineage.state.pending")
    assert _tekst_komorki(v, 21, "_rodowod", Qt.ToolTipRole) == i18n.t("grid.lineage.tip.mixed")
    assert "(zmieniona)" not in v.combo_persp.currentText()


def test_komorka_lightu_jest_pusta_a_facet_staje_tylko_nad_gotowymi_obrazami(strona):
    """Grupa „Rodowód" w listwie wchodzi, gdy zbiór to same gotowe obrazy (albo facet ma wybór) -
    nad zbiorem mieszanym podnosiłaby podłogę okna dla pytania o jeden rodzaj."""
    v = strona.frames_view
    assert _tekst_komorki(v, 1, "_rodowod") == ""
    assert _tekst_komorki(v, 1, "_rodowod", Qt.ToolTipRole) is None
    lw, tytul = v.facet_rail._lists["lineage"], v.facet_rail._tytuly["lineage"]
    assert not lw.isVisibleTo(v.facet_rail) and not tytul.isVisibleTo(v.facet_rail)   # mieszany
    v._facet_state = {"kind": {"in": [["master_light", "master_light"]]}}
    v.refresh()
    assert lw.isVisibleTo(v.facet_rail) and tytul.isVisibleTo(v.facet_rail)
    v._facet_state = {"lineage": {"in": [["window", "z okna czasu"]]}}
    v.refresh()
    assert v._frame_ids == [10] and lw.isVisibleTo(v.facet_rail)   # wybór trzyma grupę
    v._facet_state = {"kind": {"in": [["light", "light"]]}}
    v.refresh()
    assert not lw.isVisibleTo(v.facet_rail)


def _klik_facetu(rail, facet, wartosc):
    lw = rail._lists[facet]
    for i in range(lw.count()):
        dane = lw.item(i).data(Qt.UserRole)
        if dane and dane[1] == wartosc:
            QApplication.processEvents()
            lw.scrollToItem(lw.item(i))
            rect = lw.visualItemRect(lw.item(i))
            QTest.mouseClick(lw.viewport(), Qt.LeftButton, Qt.NoModifier, rect.center())
            QApplication.processEvents()
            return
    raise AssertionError(f"brak wartości {wartosc!r} w facecie {facet}")


def test_facet_rodowodu_zaweza_a_liczniki_sa_sibling_set(strona, con):
    """Klik „do potwierdzenia" zawęża do stosu 24; liczniki pozostałych stanów zostają (OR wewnątrz
    facetu osiągalny), a drugi klik w inny stan sumuje zbiory."""
    _seed_stany(con)
    v = strona.frames_view
    v.apply_perspective(grid_mod.PRESET_READY_IMAGES)
    _klik_facetu(v.facet_rail, "lineage", "pending")
    assert v._frame_ids == [24]
    lw = v.facet_rail._lists["lineage"]
    widoczne = {lw.item(i).data(Qt.UserRole)[1] for i in range(lw.count())
                if lw.item(i).data(Qt.UserRole)}
    assert widoczne == set(queries.LINEAGE_STATES)     # sibling-set: komplet stanów
    _klik_facetu(v.facet_rail, "lineage", "uncounted")
    assert sorted(v._frame_ids) == [24, 27]
    assert "(zmieniona)" not in v.combo_persp.currentText()   # zawężenie W RAMACH presetu


# ---------- R3: „Cofnij" w komunikacie po werdykcie ----------

def _klik(btn):
    QApplication.processEvents()
    QTest.mouseClick(btn, Qt.LeftButton)
    QApplication.processEvents()


def _wiersz_listy(lista, frame_id):
    for i in range(lista.count()):
        if lista.item(i).data(Qt.UserRole) == frame_id:
            return lista.item(i)
    raise AssertionError(f"brak klatki {frame_id} na liście")


def _stan_wejscia(con, frame_id, integration_id=5):
    r = con.execute("SELECT asserted_by, excluded FROM integration_input "
                    "WHERE integration_id = ? AND input_frame_id = ?",
                    (integration_id, frame_id)).fetchone()
    return None if r is None else (r["asserted_by"], r["excluded"])


def test_cofnij_po_odrzuceniu_wraca_do_stanu_sprzed_gestu(strona, con):
    """D-1011-4: „Odrzuć" na wejściu z okna, potem „Cofnij" z recepty paska = wiersz znów `window`,
    nie `user` z werdyktem przeciwnym. Kolumna „Rodowód" idzie za gestem bez przeładowania."""
    v = strona.frames_view
    recepty = []
    v.status_recipe.connect(recepty.append)
    _zaznacz(v, [10])
    v._toggle_panel("lineage")
    _wiersz_listy(v.lineage_bar.items, 2).setSelected(True)
    _klik(v.lineage_bar.btn_reject)
    assert _stan_wejscia(con, 2) == ("user", 1)
    assert _tekst_komorki(v, 10, "_rodowod") == i18n.t("grid.lineage.state.window")
    recepta = recepty[-1]
    assert str(recepta) == i18n.t("grid.lin.undo")
    assert recepta.czlony[0].wykonaj is not None
    recepta.czlony[0].wykonaj()
    assert _stan_wejscia(con, 2) == ("window", 0)
    assert str(recepty[-1]) == ""                       # recepta zeszła z paska
    assert _zaznaczone(v) == [10]
    assert v.lineage_bar.selected_frame_ids() == [2]    # wiersz cofniętego gestu zaznaczony
    zdarzenia = con.execute("SELECT verb FROM event WHERE verb LIKE 'integration.judg%' "
                            "ORDER BY id").fetchall()
    assert [z["verb"] for z in zdarzenia] == ["integration.judged", "integration.judgment_restored"]


def test_potwierdzenie_zmienia_kolumne_a_zaznaczenie_przezywa_przeladowanie(strona, con):
    """Potwierdzenie wejścia z okna: zbiór liczony od nowa, stos przechodzi z „z okna" na
    „częściowo potwierdzony", a zaznaczenie stosu i wiersza listy zostaje (wiz #8)."""
    v = strona.frames_view
    _zaznacz(v, [10])
    v._toggle_panel("lineage")
    _wiersz_listy(v.lineage_bar.items, 1).setSelected(True)
    _klik(v.lineage_bar.btn_confirm)
    assert _tekst_komorki(v, 10, "_rodowod") == i18n.t("grid.lineage.state.mixed")
    assert _zaznaczone(v) == [10]
    assert v.lineage_bar.selected_frame_ids() == [1]


def _klik_wiersza(lista, frame_id, modyfikator=Qt.NoModifier):
    QApplication.processEvents()
    it = _wiersz_listy(lista, frame_id)
    lista.scrollToItem(it)
    QTest.mouseClick(lista.viewport(), Qt.LeftButton, modyfikator, lista.visualItemRect(it).center())
    QApplication.processEvents()


def test_werdykt_na_dwoch_zaznaczonych_wierszach_to_jeden_gest_z_jednym_cofnieciem(strona, con):
    """dwa wiersze zaznaczone myszą (klik + Ctrl+klik), jedno „Odrzuć" = jedna klinga zbiorcza,
    a „Cofnij" zdejmuje oba werdykty naraz."""
    v = strona.frames_view
    _zaznacz(v, [10])
    v._toggle_panel("lineage")
    lista = v.lineage_bar.items
    _klik_wiersza(lista, 1)
    _klik_wiersza(lista, 2, Qt.ControlModifier)
    assert sorted(v.lineage_bar.selected_frame_ids()) == [1, 2]
    _klik(v.lineage_bar.btn_reject)
    assert _stan_wejscia(con, 1) == _stan_wejscia(con, 2) == ("user", 1)
    assert [z.input_frame_id for z in v._migawka_werdyktu[2]] == [1, 2]
    v._wykonaj_odwrot((10,), grid_model._ODWROT_WERDYKTU)
    assert _stan_wejscia(con, 1) == _stan_wejscia(con, 2) == ("window", 0)


def test_awaria_drugiego_zapisu_nie_zostawia_pierwszego(strona, con, monkeypatch):
    """Falsyfikator: drugi zapis gestu pada → pierwszy nie zostaje w bazie (jedna transakcja)."""
    from horreum import repo
    v = strona.frames_view
    _zaznacz(v, [10])
    v._toggle_panel("lineage")
    prawdziwa = repo.judge_integration_input
    wolania = []

    def _druga_pada(con_, **kw):
        wolania.append(kw["input_frame_id"])
        if len(wolania) == 2:
            raise RuntimeError("awaria w połowie gestu")
        return prawdziwa(con_, **kw)

    monkeypatch.setattr(repo, "judge_integration_input", _druga_pada)
    with pytest.raises(RuntimeError):
        v._on_lineage_judged([1, 2], True)
    assert _stan_wejscia(con, 1) == _stan_wejscia(con, 2) == ("window", 0)


def test_cofnij_potwierdzenia_kandydata_usuwa_wiersz_reki(strona, con):
    """Wiersz, którego przed gestem nie było, po „Cofnij" znika (automat odtworzy swój)."""
    v = strona.frames_view
    _zaznacz(v, [10])
    v._toggle_panel("lineage")
    v._on_lineage_judged([3], False)                   # klatka 3 nie była wejściem
    assert _stan_wejscia(con, 3) == ("user", 0)
    v._wykonaj_odwrot((10,), grid_model._ODWROT_WERDYKTU)
    assert _stan_wejscia(con, 3) is None


def test_recepta_gasnie_gdy_nowszy_zapis_przykryl_gest(strona, con):
    v = strona.frames_view
    recepty = []
    v.status_recipe.connect(recepty.append)
    _zaznacz(v, [10])
    v._toggle_panel("lineage")
    v._on_lineage_judged([1], True)
    assert v._ile_werdyktow_do_cofniecia((10,)) == 1
    con.execute("UPDATE integration_input SET excluded = 0 WHERE input_frame_id = 1")
    con.commit()
    assert v._ile_werdyktow_do_cofniecia((10,)) == 0
    v.ponow_recepte()
    assert str(recepty[-1]) == ""


def test_powtorzony_werdykt_bez_zmiany_nie_daje_recepty(strona, con):
    v = strona.frames_view
    recepty = []
    v.status_recipe.connect(recepty.append)
    _zaznacz(v, [10])
    v._toggle_panel("lineage")
    v._on_lineage_judged([1], True)
    v._on_lineage_judged([1], True)
    assert str(recepty[-1]) == ""


# ---------- R4: wspólny katalog nad listą ----------

def test_wspolny_katalog_raz_nad_lista_a_w_wierszu_nazwa(strona):
    v = strona.frames_view
    _zaznacz(v, [10])
    v._toggle_panel("lineage")
    bar = v.lineage_bar
    assert bar.dir_row.isVisibleTo(bar)
    assert bar.dir_path.full_text() == "/a/L/"
    assert bar.items.item(0).text().endswith("· l1.fits")
    assert "/a/L/" not in bar.items.item(0).text()
    assert bar.items.item(0).toolTip() == "/a/L/l1.fits"


def test_dwa_katalogi_zostawiaja_pelne_sciezki_a_os_kalibracji_gasi_katalog(strona, con):
    con.execute("UPDATE location SET path = '/b/M/l2.fits' WHERE frame_id = 2")
    con.commit()
    v = strona.frames_view
    _zaznacz(v, [10])
    v._toggle_panel("lineage")
    bar = v.lineage_bar
    assert not bar.dir_row.isVisibleTo(bar)
    assert bar.items.item(1).text().endswith("/b/M/l2.fits")
    con.execute("UPDATE location SET path = '/a/L/l2.fits' WHERE frame_id = 2")
    con.commit()
    v._refresh_lineage()
    assert bar.dir_row.isVisibleTo(bar)
    bar.set_calibration([{"relation": "flat", "master_frame_id": 4, "asserted_by": "horreum",
                          "master_path": "/a/C/mf4.xisf", "pending": False, "gap": None,
                          "days_apart": 1}])
    assert not bar.dir_row.isVisibleTo(bar)


def test_wspolny_katalog_sciezek_windows():
    from horreum.gui.grid_lineage import _wspolny_katalog
    assert _wspolny_katalog([r"R:\ASTRO_\LIGHTS\M31\a.fits", r"R:\ASTRO_\LIGHTS\M31\b.fits", None]) \
        == "R:\\ASTRO_\\LIGHTS\\M31\\"
    assert _wspolny_katalog([r"R:\x\a.fits", r"R:\y\b.fits"]) is None
    assert _wspolny_katalog([None, ""]) is None


# ---------- R5: memo Dostawy ----------

def test_memo_dostawy_mowi_liczniki_stosow_ze_stanu(qapp, tmp_path):
    from horreum.gui.pipeline import PipelineView
    path = str(tmp_path / "p.db")
    c = db.open_db(path)
    _seed(c)
    _seed_stany(c)
    c.close()
    view = PipelineView(path, now_fn=lambda: NOW)
    try:
        linie = view.lbl_stacks_memo.text().split("\n")
        assert linie[1] == i18n.t("pipeline.stacks_counts", all=9, with_inputs=5, without=3,
                                  uncounted=1)
        assert view.lbl_stacks_memo.toolTip() == i18n.t("pipeline.stacks_counts_tip", no_copy=0)
    finally:
        view.close()


# ---------- most gospodarza ----------

def test_most_okna_przelacza_na_Zbiory_i_ustawia_zbior(qapp, tmp_path, monkeypatch):
    from horreum.gui.app import MainWindow, NAV_DOSTAWA, STRONA_ZBIORY
    monkeypatch.setattr(MainWindow, "_pola_poza_watkiem", False)
    path = str(tmp_path / "w.db")
    c = db.open_db(path)
    _seed(c)
    c.close()
    win = MainWindow(path)
    try:
        assert win.grid_view.show_frames_fn == win.show_frames_in_collections
        win._show_view(NAV_DOSTAWA)
        win.show_frames_in_collections([1, 2], label="L", focus=2)
        assert win._strona() == STRONA_ZBIORY
        assert sorted(win.grid_view._frame_ids) == [1, 2]
    finally:
        win.close()


# ---------- tura naprawcza: jeden fakt „czeka na rękę", przeładowanie po werdykcie, Znajdź ----------

def _seed_kandydaci(con):
    """Stos 40 bez rodowodu (okno zdegenerowane) z propozycją: noc obrazu (lighty 42, 43) i noc
    późniejsza (44) - materiał trybu propozycji panelu (wzór `test_gui_grid._seed_stos_z_kandydatami`)."""
    import json
    con.execute("INSERT INTO object (id, canon, catalog, kind) VALUES (7, 'M51', 'catalog', 'deep_sky')")
    raw = {"IMAGETYP": "Master Light", "EXPTIME": 300.0,
           "DATE-OBS": "2023-04-21T20:00:00", "DATE-END": "2023-04-21T20:05:00"}
    con.execute("INSERT INTO frame (id, sha1_data, kind, filetype, object_id, filter_canon, "
                "first_seen_at) VALUES (40, 'm40', 'master_light', 'xisf', 7, 'Ha', ?)", (NOW,))
    con.execute("INSERT INTO header (frame_id, raw_json, date_obs, exptime) "
                "VALUES (40, ?, '2023-04-21T20:00:00', 300.0)", (json.dumps(raw),))
    con.execute("INSERT INTO location (frame_id, volume, path, present) "
                "VALUES (40, 'V', '/a/S/masterM51.xisf', 1)")
    con.execute("INSERT INTO integration (id, master_frame_id, created_at, degenerate, ambiguous, "
                "telescope_mismatch, unresolved_reason) VALUES (41, 40, ?, 1, 0, 0, "
                "'degenerate_window')", (NOW,))
    for fid, czas in ((42, "2023-04-21T20:00:00"), (43, "2023-04-21T21:00:00"),
                      (44, "2023-04-25T20:00:00")):
        con.execute("INSERT INTO frame (id, sha1_data, kind, filetype, object_id, filter_canon, "
                    "first_seen_at) VALUES (?, ?, 'light', 'fits', 7, 'Ha', ?)", (fid, f"k{fid}", NOW))
        con.execute("INSERT INTO header (frame_id, raw_json, date_obs, exptime) "
                    "VALUES (?, '{}', ?, 300.0)", (fid, czas))
        con.execute("INSERT INTO location (frame_id, volume, path, present) VALUES (?, 'V', ?, 1)",
                    (fid, f"/a/M/l{fid}.fits"))
    con.commit()


def test_odrzucenie_ostatniego_kandydata_zdejmuje_stos_z_kolejki(strona, con):
    """od „do potwierdzenia" do odrzucenia OSTATNIEGO kandydata prawdziwymi kliknięciami. Póki
    zostaje nieosądzony kandydat (druga noc), stos czeka; po ostatnim - „wszystkie odrzucone",
    poza perspektywą „Rodowód do potwierdzenia", a panel nie proponuje pustych nocy."""
    _seed_kandydaci(con)
    v = strona.frames_view
    assert queries.stack_lineage_states(con)[40] == "pending"
    v.refresh()
    _zaznacz(v, [40])
    v._toggle_panel("lineage")
    bar = v.lineage_bar
    assert bar.combo_night.count() == 2 and bar.items.count() == 2
    _klik_wiersza(bar.items, 42)
    _klik_wiersza(bar.items, 43, Qt.ControlModifier)
    _klik(bar.btn_reject)
    assert 40 in queries.lineage_pending_frame_ids(con)            # noc 2023-04-25 nieosądzona
    assert queries.stack_lineage_states(con)[40] == "pending"
    bar.combo_night.setCurrentIndex(bar.combo_night.findData("2023-04-25"))
    _klik_wiersza(bar.items, 44)
    _klik(bar.btn_reject)
    assert 40 not in queries.lineage_pending_frame_ids(con)
    assert queries.stack_lineage_states(con)[40] == "rejected"
    assert _tekst_komorki(v, 40, "_rodowod") == i18n.t("grid.lineage.state.rejected")
    assert bar.night_row.isHidden()                                # bez pustych nocy
    assert sorted(bar.items.item(i).data(Qt.UserRole) for i in range(bar.items.count())) \
        == [42, 43, 44]                                            # własne werdykty do cofnięcia


def test_werdykt_przy_facecie_do_potwierdzenia_przelicza_zbior_i_liczniki(strona, con):
    """aktywny facet „do potwierdzenia" - potwierdzony stos ZNIKA ze zbioru, a licznik facetu
    mówi o nowym stanie; stos nie stoi pod filtrem, któremu przeczy."""
    _seed_kandydaci(con)
    v = strona.frames_view
    v.apply_perspective(grid_mod.PRESET_READY_IMAGES)
    _klik_facetu(v.facet_rail, "lineage", "pending")
    assert v._frame_ids == [40]
    _zaznacz(v, [40])
    v._toggle_panel("lineage")
    _klik_wiersza(v.lineage_bar.items, 42)
    _klik(v.lineage_bar.btn_confirm)
    assert v._frame_ids == []
    lw = v.facet_rail._lists["lineage"]
    liczniki = {lw.item(i).data(Qt.UserRole)[1]: lw.item(i).text() for i in range(lw.count())
                if lw.item(i).data(Qt.UserRole)}
    assert "exact" in liczniki and "window" in liczniki   # stos 40 przeszedł do „dokładny"
    from horreum.gui import rows
    pending = [lw.item(i) for i in range(lw.count())
               if lw.item(i).data(Qt.UserRole) and lw.item(i).data(Qt.UserRole)[1] == "pending"]
    assert pending[0].data(rows.SECONDARY) == "(0)"     # wybór przypięty, licznik ze stanu po geście


def test_zastapiony_stos_nie_czeka_na_reke(con):
    """zastąpiony stos z aktualnym powodem jest historią, nie robotą - symetrycznie do
    wycofanego. W „Gotowych obrazach" stoi jako „brak" (nie czeka na gest)."""
    _seed_kandydaci(con)
    assert 40 in queries.lineage_pending_frame_ids(con)
    con.execute("UPDATE frame SET superseded_by = 10 WHERE id = 40")
    con.commit()
    assert 40 not in queries.lineage_pending_frame_ids(con)
    assert queries.stack_lineage_states(con)[40] == "none"
    assert not queries.lineage_awaits_hand(con, 40)


def test_chip_wraca_do_zapytania_Znajdz_z_jego_tekstem(strona, con):
    """dwuklik z aktywnego Znajdź, potem „×" - wraca zbiór ORAZ zapytanie: pole, terminy,
    tekst uwag i to, że zbiór dalej jest zbiorem tego zapytania."""
    con.execute("INSERT INTO frame_note (frame_id, body, updated_at) VALUES (10, 'stos gotowy', ?)",
                (NOW,))
    con.commit()
    v = strona.frames_view
    strona.show_find("uwagi:gotowy")
    assert v._frame_ids == [10] and v.zapytanie_aktualne()
    terminy = list(v._terminy)
    _zaznacz(v, [10])
    v._toggle_panel("lineage")
    _dwuklik(v.lineage_bar.items, 0)
    assert sorted(v._frame_ids) == [1, 2]
    assert strona.pole.text() == "uwagi:gotowy"                    # nakładka nie czyści pola
    chip = next(c for c in strona._pula if c.isVisible() and c.klucz == ("wskazane",))
    QTest.mouseClick(chip, Qt.LeftButton)
    QApplication.processEvents()
    assert v._frame_ids == [10]
    assert strona.pole.text() == "uwagi:gotowy"
    assert v.note_query == "gotowy" and v._terminy == terminy
    assert v.zapytanie_aktualne()


def test_sklad_liczy_stan_rodowodu_raz(strona, con, monkeypatch):
    """jeden skład zbioru = jedno policzenie read-modelu rodowodu, także z aktywnym facetem
    (kolumna, liść facetu, widoczność grupy i liczniki czytają ten sam słownik)."""
    _seed_stany(con)
    v = strona.frames_view
    v.apply_perspective(grid_mod.PRESET_READY_IMAGES)
    v._facet_state = {**v._facet_state, "lineage": {"in": [["pending", "do potwierdzenia"],
                                                           ["window", "z okna czasu"]]}}
    wolania = []
    prawdziwa = queries.stack_lineage_states
    monkeypatch.setattr(queries, "stack_lineage_states",
                        lambda c: wolania.append(1) or prawdziwa(c))
    v.refresh()
    assert sorted(v._frame_ids) == [10, 20, 24]
    assert len(wolania) == 1


# ---------- tura po wizytacji natywnej ----------

def test_werdykt_podzbioru_okna_naglowek_mowi_N_a_ostrzezenie_sprawe(strona, con):
    """„plik użył N z M" - nagłówek nie mówi „Weszły M", tylko okno M i użyte N (≈ godziny);
    zdanie o podzbiorze stoi w ostrzeżeniu, nie w nocie."""
    con.execute("UPDATE integration SET used_rows = 1 WHERE id = 5")
    con.commit()
    v = strona.frames_view
    _zaznacz(v, [10])
    v._toggle_panel("lineage")
    bar = v.lineage_bar
    # 2 wejścia × 300 s = 600 s, plik użył 1 z 2 → ≈300 s = 0.1 h
    assert bar.head.text() == i18n.t_plural("grid.lin.head_subset", 2, used=1, hours="0.1")
    assert i18n.t_plural("grid.lin.flag.used_rows_warn", 2, used=1) in bar.warn.full_text()
    assert "plik użył" not in bar.note.full_text()


def test_powod_no_candidates_przy_materiale_mowi_tylko_o_oknie(strona, con):
    """`no_candidates` przy kandydatach w propozycji nie twierdzi, że archiwum nic nie ma."""
    from horreum.gui.grid_lineage import REASON_NO_CANDIDATES_TOKEN
    from horreum.stacks import REASON_NO_CANDIDATES
    assert REASON_NO_CANDIDATES_TOKEN == REASON_NO_CANDIDATES      # lustro tokenu rdzenia
    _seed_kandydaci(con)
    con.execute("UPDATE integration SET unresolved_reason = 'no_candidates' WHERE id = 41")
    con.commit()
    v = strona.frames_view
    v.refresh()
    _zaznacz(v, [40])
    v._toggle_panel("lineage")
    assert v.lineage_bar.head.text() == i18n.t("grid.lin.reason.no_candidates_window")


def test_przeladowanie_po_werdykcie_nie_zaglusza_zdania_gestu(strona, con):
    """raport wczytania („Grid: N klatek") po przeładowaniu wywołanym gestem milczy - ostatnim
    słowem na pasku zostaje zdanie gestu. Zwykłe przeładowanie raportuje dalej."""
    v = strona.frames_view
    raporty, zdania = [], []
    v.load_report.connect(raporty.append)
    v.status_message.connect(zdania.append)
    _zaznacz(v, [10])
    v._toggle_panel("lineage")
    _wiersz_listy(v.lineage_bar.items, 2).setSelected(True)
    _klik(v.lineage_bar.btn_reject)
    wczytane = i18n.t("grid.status.loaded", frames="", cols=0).split(":")[0]
    assert not any(r.startswith(wczytane) for r in raporty)
    assert zdania[-1] == i18n.t("grid.lin.judged_excluded", n=1)
    v.refresh()
    assert any(r.startswith(wczytane) for r in raporty)


def test_gotowe_obrazy_chowa_dh_eliduje_srodek_i_maluje_stany_rolami(strona, con):
    """w presecie „Gotowe obrazy" Δh ukryta, ścieżka elidowana w środku, belka
    „do potwierdzenia" pierwsza, stan „do potwierdzenia" w roli warn, „z okna czasu" w secondary."""
    _seed_stany(con)
    v = strona.frames_view
    v.apply_perspective(grid_mod.PRESET_READY_IMAGES)
    m = v.model
    assert v.table.isColumnHidden(m.base_col("_dt_delta"))
    assert isinstance(v.table.itemDelegateForColumn(m.base_col("path")), grid_model._ElizjaWSrodku)
    assert [r["_group"] for r in m._rows if "_group" in r][0] == i18n.t("grid.lineage.state.pending")
    robota = _tekst_komorki(v, 24, "_rodowod", Qt.ForegroundRole)
    okno = _tekst_komorki(v, 20, "_rodowod", Qt.ForegroundRole)
    assert robota == grid_model._COLORS["warn"] and okno == grid_model._COLORS["secondary_text"]
    assert robota.name() != okno.name()              # robota odróżnia się od niepotwierdzonego
    v.apply_perspective("Przegląd")
    assert not v.table.isColumnHidden(m.base_col("_dt_delta"))
    assert v.table.itemDelegateForColumn(m.base_col("path")) is None


def test_grupa_rodowodu_miesci_wartosci_bez_suwaka_a_listwa_sie_przewija(strona, con):
    """STRUKTURALNIE (wartość podłogi mierzy się natywnie, nie tu): listwa stoi
    w przewijanym kontenerze, a grupa „Rodowód" ma wysokość dopasowaną do liczby wartości."""
    from PySide6.QtWidgets import QScrollArea
    _seed_stany(con)
    v = strona.frames_view
    assert isinstance(v.rail_box, QScrollArea) and v.rail_box.widget() is v.facet_rail
    v.apply_perspective(grid_mod.PRESET_READY_IMAGES)
    lw = v.facet_rail._lists["lineage"]
    wiersz = lw.sizeHintForRow(0)
    assert lw.count() == 8
    assert lw.height() == 6 * wiersz + 2 * lw.frameWidth()          # sufit 6 przy 8 wartościach
    _klik_facetu(v.facet_rail, "lineage", "pending")
    v._facet_state = {"kind": {"in": [["master_light", "master_light"]]}}
    con.execute("DELETE FROM integration_input WHERE integration_id IN (21, 22, 23)")
    con.commit()
    v.refresh()
    assert lw.height() == lw.count() * wiersz + 2 * lw.frameWidth()   # mniej wartości - bez pustki
    assert lw.verticalScrollBar().maximum() == 0


def test_kandydat_ma_nazwe_pliku_a_odrzucone_stoja_wygaszone(strona, con):
    """wiersz propozycji niesie nazwę pliku; odrzucony kandydat nie znika z listy - stoi
    wygaszony pod propozycjami (da się go zaznaczyć i potwierdzić)."""
    _seed_kandydaci(con)
    v = strona.frames_view
    v.refresh()
    _zaznacz(v, [40])
    v._toggle_panel("lineage")
    bar = v.lineage_bar
    assert bar.items.item(0).text().endswith("· l42.fits")
    _klik_wiersza(bar.items, 42)
    _klik(bar.btn_reject)
    assert bar.combo_night.count() == 2                          # wciąż tryb propozycji
    odrzucony = _wiersz_listy(bar.items, 42)
    assert odrzucony.foreground().color() == grid_model._COLORS["secondary_text"]
    _klik_wiersza(bar.items, 42)
    _klik(bar.btn_confirm)
    assert _stan_wejscia(con, 42, integration_id=41) == ("user", 0)
