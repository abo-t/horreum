"""Znajdź na żywym `FramesView` (offscreen): prezentacje bez przeładowania zbioru, prosty zestaw
kolumn, pasek czasowników, chipy aktywnego stanu, `note_query` (zawężenie, widoczność w klasycznej,
kto go zdejmuje), FH-12 (sufiks „(zmieniona)" i manifest), AR-50 (5) (kolumna „Wersja" do włączenia)
oraz gest „Uwagi…" z receptą „Cofnij uwagi" i odmowami przy zajętości.

Wstawianie wierszy surowym SQL dozwolone w `tests/` (meta-test AST skanuje tylko pakiet `horreum`);
uwagi, które mają mieć dziennik, piszemy klingą `repo`, jak robi to gest."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, QEvent, Qt, QThread
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from horreum import db, repo
from horreum.gui import grid as grid_mod, i18n, queries
from horreum.gui.note_dialog import NoteIntent

NOW = "2026-10-09T12:00:00"


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


def _seed(con):
    """Pięć klatek, dwa teleskopy, dwie kamery, trzy zestawy:
      1: M42 Ha    RC8+ASI2600MM    noc 2026-08-08  300 s
      2: M42 OIII  RC8+ASI2600MM    noc 2026-08-08  300 s
      3: LMC Ha    Askar 103+ASI294MC noc 2026-08-01 120 s  (alias „Large Magellanic Cloud")
      4: master_flat Ha RC8+ASI2600MM, bez nagłówka
      5: NGC7000 L-Pro RC8+ASI294MC  noc 2026-07-30  600 s"""
    con.execute("INSERT INTO camera (id, model_canon, created_at) VALUES (1, 'ASI2600MM', ?)", (NOW,))
    con.execute("INSERT INTO camera (id, model_canon, created_at) VALUES (2, 'ASI294MC', ?)", (NOW,))
    con.executemany(
        "INSERT INTO telescope (id, telescop_canon, label, status, merged_into, created_at) "
        "VALUES (?,?,?,?,?,?)",
        [(1, "RC8", None, "proposed", None, NOW), (2, "ASKAR103", "Askar 103", "approved", None, NOW)])
    con.executemany(
        "INSERT INTO config (id, telescope_id, camera_id, status, created_at) VALUES (?,?,?,?,?)",
        [(1, 1, 1, "proposed", NOW), (2, 2, 2, "proposed", NOW), (3, 1, 2, "proposed", NOW)])
    con.executemany("INSERT INTO object (id, canon, catalog) VALUES (?,?,?)",
                    [(1, "M42", "Messier"), (2, "LMC", None), (3, "NGC7000", "NGC")])
    con.execute("INSERT INTO object_alias (object_id, alias_norm, source) "
                "VALUES (2, 'LARGEMAGELLANICCLOUD', 'user')")
    con.executemany(
        "INSERT INTO frame (id, sha1_data, kind, filetype, config_id, camera_id, object_id, "
        "filter_canon, first_seen_at) VALUES (?,?,?,?,?,?,?,?,?)",
        [(1, "d1", "light", "fits", 1, 1, 1, "Ha", NOW),
         (2, "d2", "light", "fits", 1, 1, 1, "OIII", NOW),
         (3, "d3", "light", "fits", 2, 2, 2, "Ha", NOW),
         (4, "d4", "master_flat", "xisf", 1, 1, None, "Ha", NOW),
         (5, "d5", "light", "fits", 3, 2, 3, "L-Pro", NOW)])
    con.executemany(
        "INSERT INTO header (frame_id, raw_json, object_raw, date_obs, exptime) VALUES (?,?,?,?,?)",
        [(1, "{}", "M42", "2026-08-08T22:00:00", 300.0), (2, "{}", "M42", "2026-08-08T23:00:00", 300.0),
         (3, "{}", "LMC", "2026-08-01T21:00:00", 120.0), (5, "{}", "NGC7000", "2026-07-30T22:00:00", 600.0)])
    con.executemany(
        "INSERT INTO location (frame_id, volume, path, present) VALUES (?,?,?,?)",
        [(1, "V", "/a/m42_ha_1.fits", 1), (2, "V", "/a/m42_oiii_2.fits", 1),
         (3, "V", "/a/lmc_3.fits", 1), (4, "V", "/a/mf_4.xisf", 1), (5, "V", "/a/ngc_5.fits", 1)])
    con.executemany(
        "INSERT INTO cards (frame_id, keyword, idx, value_raw, value_num, value_type) VALUES (?,?,?,?,?,?)",
        [(f, "EXPTIME", 0, "300", 300.0, "float") for f in (1, 2, 3, 5)]
        + [(f, "OBJECT", 0, "X", None, "str") for f in (1, 2, 3, 5)])
    con.commit()


@pytest.fixture
def con(tmp_path):
    c = db.open_db(str(tmp_path / "z.db"))
    _seed(c)
    yield c
    c.close()


@pytest.fixture
def strona(qapp, con):
    from horreum.gui.flows.znajdz_view import ZnajdzView
    v = grid_mod.FramesView(con, now_fn=lambda: NOW)
    v._writeback_async = False
    s = ZnajdzView(v)
    yield s
    if not any(t.isRunning() for t in v.findChildren(QThread)):
        s.close()
        s.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def _ids(v):
    return sorted(v._frame_ids)


def _naglowki(v):
    m, h = v.model, v.table.horizontalHeader()
    return [m.headerData(h.logicalIndex(p), Qt.Horizontal, Qt.DisplayRole)
            for p in range(h.count()) if not h.isSectionHidden(h.logicalIndex(p))]


def _zaznacz(v, ids):
    v.table.clearSelection()
    v._przywroc_zaznaczenie(ids)


# ---------- prezentacje ----------

def test_klasyczna_to_dzisiejszy_ekran_a_Znajdz_prosty_zestaw_kolumn(strona):
    v = strona.frames_view
    assert v.prezentacja == grid_mod.PREZENTACJA_KLASYCZNA
    klasyczne = _naglowki(v)
    assert klasyczne[:len(grid_mod.BASE_COLS) - 1] == [
        i18n.t(k) for k, _ in grid_mod.BASE_COLS if k != "grid.col.images"]
    strona.show_find()
    assert _naglowki(v) == ["Obiekt", "Noc", "Filtr", "Czas", "Zestaw", "Uwagi", "Plik"]
    assert not v.filter_panel.isVisibleTo(v) and not v.fields.isVisibleTo(v)
    strona.show_classic()
    assert _naglowki(v) == klasyczne
    assert v.filter_panel.isVisibleTo(v) and v.fields.isVisibleTo(v)


def test_przelaczenie_prezentacji_NIE_przeladowuje_zbioru_i_zachowuje_zaznaczenie(strona, monkeypatch):
    v = strona.frames_view
    _zaznacz(v, [2, 3])
    wolania = []
    prawdziwy = grid_mod._sklad_zbioru
    monkeypatch.setattr(grid_mod, "_sklad_zbioru", lambda *a, **k: wolania.append(1) or prawdziwy(*a, **k))
    gen = v._zbior_gen
    strona.show_find()
    strona.show_classic()
    strona.show_find()
    assert wolania == [] and v._zbior_gen == gen, "przełączenie prezentacji przeładowało zbiór"
    assert sorted(r["frame_id"] for r in v._selected_data_rows()) == [2, 3]


def test_kolumny_Znajdz_mowia_noca_czasem_zestawem_i_uwaga(strona, con):
    repo.set_frame_note(con, frame_ids=[3], body="chmury od północy " * 10, now=NOW)
    v = strona.frames_view
    v.refresh()
    strona.show_find()
    m = v.model
    wiersz = next(i for i, r in enumerate(m._rows) if r.get("frame_id") == 3)
    komorka = {k: m.data(m.index(wiersz, m.base_col(k)), Qt.DisplayRole)
               for k in ("_object", "night", "filter_canon", "exptime", "_zestaw", "path")}
    assert komorka == {"_object": "LMC", "night": "2026-08-01", "filter_canon": "Ha",
                       "exptime": "120 s", "_zestaw": "Askar 103 · ASI294MC", "path": "lmc_3.fits"}
    pelna = queries.notes_for(con, [3])[3]
    assert m.data(m.index(wiersz, m.base_col("note")), Qt.ToolTipRole) == pelna
    assert v.table.columnWidth(m.base_col("note")) == grid_mod._SZEROKOSC_UWAG


def test_etykiety_kolumn_Znajdz_sa_w_katalogu(strona):
    from horreum.gui.i18n_catalog import CATALOG
    assert not [k for k, _ in grid_mod.FIND_COLS if k not in CATALOG]


def test_pasek_czasownikow_Znajdz_i_klasyczny_bez_zmian(strona):
    bar = strona.frames_view.sel_bar
    klasyczny = [w for w in bar._rzad() if w is not None]
    assert klasyczny == [bar.btn_clear, bar.btn_proj, bar.btn_obj, bar.btn_macro, bar.btn_rename,
                         bar.btn_lineage, bar.btn_object, bar.btn_frame, bar.btn_save]
    strona.show_find()
    widoczne = [w for w in bar._rzad() if w is not None]
    assert [w.text() for w in widoczne[1:]] == [
        "Wydaj do WBPP", "Popraw nagłówki…", i18n.t("grid.sel.object"), i18n.t("grid.sel.lineage"),
        "Uwagi…", "Kolumny", i18n.t("nav.zbiory")]
    assert all(w.isVisibleTo(bar) for w in widoczne)
    assert not any(w.isVisibleTo(bar) for w in (bar.btn_proj, bar.btn_rename, bar.btn_frame,
                                                 bar.btn_save))
    strona.show_classic()
    assert bar.btn_obj.text() == i18n.t("grid.sel.release_object")
    assert not bar.btn_notes.isVisibleTo(bar) and not bar.btn_classic.isVisibleTo(bar)


def test_Wydaj_do_WBPP_to_ta_sama_droga_co_Wydaj_obiekt(strona, monkeypatch):
    """Czasownik Znajdź to TEN SAM przycisk i ta sama droga (okno teczek z podpowiedzią obiektu
    zbioru) - nie druga kopia wydania."""
    v = strona.frames_view
    wolane = []

    class _Teczki:
        def __init__(self, con, *, preselect=None, parent=None):
            wolane.append(preselect)

        def exec(self):
            return 0

    monkeypatch.setattr(grid_mod, "ObjectPickDialog", _Teczki)
    strona.show_find("m42")
    v.sel_bar.btn_obj.click()
    assert wolane == [1], "teczka obiektu zbioru zaznaczona na starcie"


def test_czasownik_Zbiory_klasyczne_przelacza_i_mowi_gospodarzowi(strona):
    zmiany = []
    strona.prezentacja_zmieniona.connect(zmiany.append)
    strona.show_find()
    strona.frames_view.sel_bar.btn_classic.click()
    assert strona.prezentacja == grid_mod.PREZENTACJA_KLASYCZNA
    assert zmiany == ["znajdz", "klasyczna"]
    strona.show_classic()
    assert zmiany == ["znajdz", "klasyczna"], "bez zmiany prezentacji sygnału nie ma"


def test_panel_nazw_plikow_bez_czasownika_zamyka_sie_w_Znajdz(strona):
    v = strona.frames_view
    v._toggle_panel("rename")
    assert v._rename_panel_open()
    strona.show_find()
    assert not v._rename_panel_open()


# ---------- zapytanie ----------

def test_Enter_w_polu_z_fokusem_stosuje_zapytanie(strona):
    """Prawdziwy klawisz przy polu z fokusem: wpisz, Enter - Znajdź = 2 interakcje."""
    strona.resize(1200, 700)
    strona.show()
    strona.activateWindow()
    QTest.qWaitForWindowActive(strona)
    strona.show_find()
    # Asercja PO obrocie pętli, nie synchronicznie: przycisk paska bez rodzica, pokazany przy
    # wejściu w Znajdź, był oknem najwyższego poziomu i zabierał aktywację - fokus ustawiony
    # w `show_find` ginął dopiero w następnym obrocie.
    QApplication.processEvents()
    assert QApplication.activeWindow() is strona
    assert strona.pole.hasFocus(), "wejście w Znajdź stawia fokus w polu"
    assert not [w for w in QApplication.topLevelWidgets()
                if w.isVisible() and w is not strona], "pasek nie rodzi okien najwyższego poziomu"
    QTest.keyClicks(strona.pole, "m42")
    QTest.keyClick(strona.pole, Qt.Key_Return)
    assert _ids(strona.frames_view) == [1, 2]


def test_zapytanie_zastepuje_caly_zbior_i_zeruje_perspektywe(strona):
    v = strona.frames_view
    v.apply_perspective(grid_mod.PRESET_DUPS)
    strona.show_find("noc:2026-08")
    assert not v._only_dups
    assert _ids(v) == [1, 2, 3]
    strona.show_find("filtr:Ha,OIII teleskop:rc8")
    assert _ids(v) == [1, 2, 4]


def test_zestaw_stawia_teleskop_w_facecie_i_kamere_w_drzewie(strona):
    v = strona.frames_view
    strona.show_find("zestaw:rc8_asi294mc")
    assert _ids(v) == [5]
    assert v._facet_state == {"telescope": {"in": [[1, "RC8"]]}}
    assert v._filter_tree["facet"] == "camera"
    assert "Kamera: ASI294MC" in v.sel_bar.criteria_label.full_text()


def test_nieznane_czesci_mowi_zdanie_a_rozpoznane_dzialaja(strona):
    strona.show_find("filtr:Hx m42")
    assert _ids(strona.frames_view) == [1, 2]
    assert strona.zdanie.isVisibleTo(strona) and "filtr:Hx" in strona.zdanie.text()
    strona.show_find("m42")
    assert not strona.zdanie.isVisibleTo(strona)


def test_fraza_bez_obiektu_szuka_w_uwagach(strona, con):
    repo.set_frame_note(con, frame_ids=[3, 5], body="Łuna od miasta", now=NOW)
    v = strona.frames_view
    strona.show_find("łuna")
    assert v.note_query == "łuna" and _ids(v) == [3, 5]
    strona.show_find("uwagi:łuna m42")
    assert _ids(v) == []


def test_liczniki_listwy_licza_na_zbiorze_przycietym_uwagami(strona, con):
    repo.set_frame_note(con, frame_ids=[3], body="chmury", now=NOW)
    """Uwagi tną jak trim - TEN SAM zbiór dostają grid i sibling-sety listwy, więc liczniki
    facetów przy `uwagi:chmury` liczą klatki z tą uwagą, nie całe archiwum."""
    v = strona.frames_view
    strona.show_find("uwagi:chmury")
    assert _ids(v) == [3]
    counts = grid_mod._sklad_zbioru(con, v._migawka_zbioru())["listwa"][0]
    assert counts["object"] == [(2, "LMC", 1)]
    assert counts["filter"] == [("Ha", "Ha", 1)]


# ---------- chipy i note_query ----------

def _widoczne(strona):
    return [c.text() for c in strona._pula if c.isVisibleTo(strona)]


def _chip(strona, poczatek):
    return next(c for c in strona._pula if c.isVisibleTo(strona) and c.text().startswith(poczatek))


def test_chip_na_WPISANY_termin_zdejmuje_wszystko_co_termin_postawil(strona):
    """Jeden chip na wpisany termin („Filtr: Ha, OIII", „Zestaw: …"), nie na każdą wartość -
    zdjęcie terminu to jeden klik. Składnik dołożony spoza zapytania (klik w listwie) ma własny chip."""
    v = strona.frames_view
    strona.show_find("m42 filtr:Ha,OIII zestaw:rc8_asi2600mm uwagi:x")
    assert _widoczne(strona) == ["Filtr: Ha, OIII  ×", "Zestaw: rc8_asi2600mm  ×",
                                 "Obiekt: m42  ×", "Uwagi: „x”  ×"]
    _chip(strona, "Uwagi").click()
    assert v.note_query is None and _ids(v) == [1, 2]
    _chip(strona, "Filtr").click()
    assert "filter" not in v._facet_state and _ids(v) == [1, 2]
    _chip(strona, "Zestaw").click()
    assert v._filter_tree is None and "telescope" not in v._facet_state
    assert _widoczne(strona) == ["Obiekt: m42  ×"]
    v._on_facet_change({**v._facet_state, "kind": {"in": [["light", "light"]]}})
    assert _widoczne(strona) == ["Obiekt: m42  ×", "Rodzaj: light  ×"]


def test_chip_miesiaca_zdejmuje_wszystkie_jego_noce_takze_po_czesciowej_zmianie(strona):
    v = strona.frames_view
    strona.show_find("noc:2026-08")
    assert _widoczne(strona) == ["Noc: 2026-08  ×"] and _ids(v) == [1, 2, 3]
    v._on_facet_change({"night": {"in": [["2026-08-08", "2026-08-08"]]}})   # listwa zdjęła jedną
    assert _widoczne(strona) == ["Noc: 2026-08  ×"]
    _chip(strona, "Noc").click()
    assert v._facet_state == {} and _ids(v) == [1, 2, 3, 4, 5]


def test_rzad_chipow_nie_podnosi_minimalnej_szerokosci_strony(strona, con):
    """Dziesiątki chipów (tu 40 wpisanych terminów nocy) nie rozpychają strony: rząd przewija się
    w poziomie. Zmierzone natywnie: chip na każdą noc roku dawał okno ~9000 px na ekranie 2560."""
    con.executemany(
        "INSERT INTO frame (id, sha1_data, kind, filetype, first_seen_at) VALUES (?,?,?,?,?)",
        [(100 + d, f"n{d}", "light", "fits", NOW) for d in range(40)])
    con.executemany(
        "INSERT INTO header (frame_id, raw_json, date_obs) VALUES (?, '{}', ?)",
        [(100 + d, f"2025-{1 + d // 28:02d}-{1 + d % 28:02d}T22:00:00") for d in range(40)])
    con.commit()
    strona.resize(1200, 700)
    strona.show()
    strona.show_find("")
    QApplication.processEvents()
    przed, szerokosc = strona.minimumSizeHint().width(), strona.width()
    noce = " ".join(f"noc:2025-{1 + d // 28:02d}-{1 + d % 28:02d}" for d in range(40))
    strona.show_find(noce)
    QApplication.processEvents()
    assert len(_widoczne(strona)) == 40
    assert strona.minimumSizeHint().width() <= przed
    assert strona.width() == szerokosc, "okno nie urosło"


def test_chip_trimu_i_wykluczenia(strona):
    v = strona.frames_view
    strona.show_find()
    v.apply_perspective(grid_mod.PRESET_DUPS)
    v._facet_state = {"kind": {"ex": [["light", "light"]]}}
    v.refresh()
    etykiety = [t for _, t in v.skladniki_stanu()]
    assert etykiety == [i18n.t("grid.criteria.only_dups"), "poza (Rodzaj: light)"]
    v.zdejmij_skladnik(("trim", "_only_dups"))
    assert not v._only_dups
    with pytest.raises(ValueError):
        v.zdejmij_skladnik(("nieznany",))


def test_note_query_jest_widoczny_w_klasycznej(strona, con):
    """Ekran nie kłamie: w klasycznej uwagi nie mają kontrolki, więc rząd chipów stoi dla nich -
    i tylko dla nich (facety i filtr mają tam listwę i panel)."""
    repo.set_frame_note(con, frame_ids=[1], body="rosa", now=NOW)
    v = strona.frames_view
    strona.show_find("uwagi:rosa filtr:Ha")
    strona.show_classic()
    assert strona.chipy.isVisibleTo(strona)
    assert [c.text() for c in strona._pula if c.isVisibleTo(strona)] == ["Uwagi: „rosa”  ×"]
    assert "uwagi zawierają „rosa”" in v.sel_bar.criteria_label.full_text()
    assert not strona.pasek.isVisibleTo(strona)
    strona._pula[0].click()
    assert v.note_query is None and not strona.chipy.isVisibleTo(strona)


def _z_uwagami(strona):
    strona.show_find("uwagi:x")
    assert strona.frames_view.note_query == "x"
    return strona.frames_view


def test_Wyczysc_zbior_zdejmuje_note_query(strona):
    v = _z_uwagami(strona)
    assert v.sel_bar.btn_clear.isEnabled(), "zbiór zawężony samymi uwagami ma czynny przycisk"
    v.sel_bar.btn_clear.click()
    assert v.note_query is None and _ids(v) == [1, 2, 3, 4, 5]


def test_wybor_perspektywy_z_listy_zdejmuje_note_query(strona):
    v = _z_uwagami(strona)
    v.combo_persp.setCurrentIndex(next(i for i in range(v.combo_persp.count())
                                       if v.combo_persp.itemData(i) == ("preset", "Kalibracja")))
    assert v.note_query is None


def test_apply_perspective_zdejmuje_note_query_takze_na_biezacej_pozycji(strona):
    v = _z_uwagami(strona)
    v.apply_perspective(grid_mod._PRESET_CZYSTY)
    assert v.note_query is None and _ids(v) == [1, 2, 3, 4, 5]


def test_most_obiektu_zdejmuje_note_query(strona):
    v = _z_uwagami(strona)
    v.apply_object_facet([(1, "M42")])
    assert v.note_query is None and _ids(v) == [1, 2]


def test_nowe_zapytanie_zastepuje_note_query(strona):
    v = _z_uwagami(strona)
    strona.show_find("m42")
    assert v.note_query is None


def test_klik_facetu_ZOSTAWIA_note_query(strona, con):
    repo.set_frame_note(con, frame_ids=[1, 3], body="x", now=NOW)
    v = _z_uwagami(strona)
    v._on_facet_change({"filter": {"in": [["Ha", "Ha"]]}})
    assert v.note_query == "x" and _ids(v) == [1, 3]


# ---------- FH-12 (tekst uwag; sufiks przy filtrze i manifest - obok BP-5 w `test_gui_grid`) ----------

def test_FH12_note_query_liczy_sie_jako_zmiana_stanu(strona):
    v = strona.frames_view
    _z_uwagami(strona)
    assert v.combo_persp.currentData() == ("preset", grid_mod._PRESET_CZYSTY)
    assert v.combo_persp.currentText().endswith("(zmieniona)")
    v.zdejmij_skladnik(("uwagi",))
    assert v.combo_persp.currentText() == i18n.t("perspective.review")


def test_FH12_EN(strona):
    i18n.set_lang("en")
    v = strona.frames_view
    _z_uwagami(strona)
    assert v.combo_persp.currentText().endswith(" (modified)")


# ---------- AR-50 (5): kolumna „Wersja" w Znajdź ----------

def test_AR50_kolumna_Wersja_do_wlaczenia_w_Znajdz_domyslnie_wylaczona(strona):
    v = strona.frames_view
    strona.show_find()
    assert v.model._version_col() is None
    v.sel_bar.act_version_col.setChecked(True)
    assert v.model._version_col() == len(grid_mod.FIND_COLS)
    assert "Wersja" in _naglowki(v)
    strona.show_classic()
    assert v.model._version_col() is None, "w klasycznej Wersja należy do perspektywy"
    strona.show_find()
    assert v.model._version_col() is not None, "wybór przeżył przełączenie"
    v.sel_bar.act_version_col.setChecked(False)
    assert v.model._version_col() is None


# ---------- gest „Uwagi…" ----------

class _Okno:
    """Atrapa `NoteDialog` - intencja ustawiona przez test, wejście zapisane do sprawdzenia."""
    intencja = None
    wejscie = None

    def __init__(self, *, current, frame_count, parent=None):
        _Okno.wejscie = (dict(current), frame_count)
        self.intent = _Okno.intencja

    def exec(self):
        return 1


@pytest.fixture
def okno(monkeypatch):
    _Okno.intencja, _Okno.wejscie = None, None
    monkeypatch.setattr(grid_mod, "NoteDialog", _Okno)
    return _Okno


@pytest.fixture
def recepty(strona):
    out = []
    strona.frames_view.status_recipe.connect(out.append)
    return out


@pytest.fixture
def statusy(strona):
    out = []
    strona.frames_view.status_message.connect(out.append)
    return out


def _uwagi(con):
    return queries.notes_for(con, [1, 2, 3, 4, 5])


def test_gest_uwag_mieszany_before_i_cofniecie_bajt_w_bajt(strona, con, okno, recepty):
    repo.set_frame_note(con, frame_ids=[1], body="stara", now=NOW)
    v = strona.frames_view
    v.refresh()
    _zaznacz(v, [1, 2])
    okno.intencja = NoteIntent("set", "chmury")
    v.sel_bar.act_notes.trigger()
    assert okno.wejscie == ({1: "stara"}, 2)
    assert _uwagi(con) == {1: "chmury", 2: "chmury"}
    rec = recepty[-1]
    assert [c.tekst for c in rec.czlony] == ["Cofnij uwagi"]
    rec.czlony[0].wykonaj()
    assert _uwagi(con) == {1: "stara"}
    assert recepty[-1].czlony == (), "po cofnięciu recepta schodzi z paska"


def test_gest_uwag_zdjecie_i_jego_cofniecie(strona, con, okno, recepty):
    repo.set_frame_note(con, frame_ids=[1, 2], body="a", now=NOW)
    v = strona.frames_view
    v.refresh()
    _zaznacz(v, [1, 2, 3])
    okno.intencja = NoteIntent("clear", None)
    v._on_notes()
    assert _uwagi(con) == {}
    recepty[-1].czlony[0].wykonaj()
    assert _uwagi(con) == {1: "a", 2: "a"}


def test_cofniecie_po_zmianie_zaznaczenia_celuje_w_klatki_gestu(strona, con, okno, recepty):
    v = strona.frames_view
    _zaznacz(v, [1, 2])
    okno.intencja = NoteIntent("set", "x")
    v._on_notes()
    _zaznacz(v, [5])
    recepty[-1].czlony[0].wykonaj()
    assert _uwagi(con) == {}
    assert sorted(r["frame_id"] for r in v._selected_data_rows()) == [1, 2]


def test_cofniecie_przy_zajetosci_odmawia_a_recepta_zostaje(strona, con, okno, recepty, statusy):
    v = strona.frames_view
    _zaznacz(v, [1])
    okno.intencja = NoteIntent("set", "x")
    v._on_notes()
    v.set_busy(True)
    recepty[-1].czlony[0].wykonaj()
    assert _uwagi(con) == {1: "x"}
    assert statusy[-1] == i18n.t("grid.recipe.busy_stage")
    assert [c.tekst for c in recepty[-1].czlony] == ["Cofnij uwagi"]
    v.set_busy(False)
    recepty[-1].czlony[0].wykonaj()
    assert _uwagi(con) == {}


def test_podwojny_klik_cofniecia_nie_cofa_drugi_raz(strona, con, okno, recepty):
    v = strona.frames_view
    _zaznacz(v, [1])
    okno.intencja = NoteIntent("set", "x")
    v._on_notes()
    rec = recepty[-1]
    rec.czlony[0].wykonaj()
    zdarzenia = con.execute("SELECT COUNT(*) FROM event").fetchone()[0]
    rec.czlony[0].wykonaj()
    assert con.execute("SELECT COUNT(*) FROM event").fetchone()[0] == zdarzenia
    assert _uwagi(con) == {}


def test_pozniejsza_edycja_gasi_recepte_a_czesciowa_cofa_tylko_reszte(strona, con, okno, recepty):
    v = strona.frames_view
    _zaznacz(v, [1, 2])
    okno.intencja = NoteIntent("set", "x")
    v._on_notes()
    repo.set_frame_note(con, frame_ids=[1], body="inna", now=NOW)
    v.ponow_recepte()
    assert [c.tekst for c in recepty[-1].czlony] == ["Cofnij uwagi"], "klatka 2 wciąż niesie gest"
    recepty[-1].czlony[0].wykonaj()
    assert _uwagi(con) == {1: "inna"}, "późniejsza decyzja na klatce 1 nietknięta"

    _zaznacz(v, [3])
    okno.intencja = NoteIntent("set", "y")
    v._on_notes()
    repo.set_frame_note(con, frame_ids=[3], body="z", now=NOW)
    v.ponow_recepte()
    assert recepty[-1].czlony == (), "edycja całego celu gasi receptę"


def test_gest_bez_zmiany_nie_daje_recepty(strona, con, okno, recepty):
    repo.set_frame_note(con, frame_ids=[1], body="x", now=NOW)
    v = strona.frames_view
    v.refresh()
    _zaznacz(v, [1])
    okno.intencja = NoteIntent("set", "x")
    v._on_notes()
    assert recepty[-1].czlony == ()


def test_uwagi_bez_zaznaczenia_wygaszone_z_podpowiedzia(strona, okno):
    v = strona.frames_view
    v.table.clearSelection()
    assert not v.sel_bar.btn_notes.isEnabled() and not v.sel_bar.act_notes.isEnabled()
    assert v.sel_bar.btn_notes.toolTip() == i18n.t("grid.notes.tip_empty")
    v._on_notes()
    assert okno.wejscie is None
    _zaznacz(v, [1, 2])
    assert v.sel_bar.btn_notes.isEnabled() and v.sel_bar.act_notes.isEnabled()
    assert v.sel_bar.btn_frame.isEnabled(), "menu „Klatka ▾” niesie uwagi także nad żywymi plikami"


@pytest.mark.parametrize("stan,klucz", [("etap", "grid.notes.busy_stage"),
                                        ("zapis", "grid.notes.busy_write"),
                                        ("droga", "grid.sel.loading_refused")])
def test_gest_uwag_odmawia_przy_zajetosci_przed_oknem(strona, con, okno, statusy, stan, klucz):
    v = strona.frames_view
    _zaznacz(v, [1])
    if stan == "etap":
        v.set_busy(True)
    elif stan == "zapis":
        v.set_writeback_busy(True)
    else:
        v._zbior_ponow = True
    v._on_notes()
    v._zbior_ponow = False
    assert okno.wejscie is None and _uwagi(con) == {}
    assert statusy[-1] == i18n.t(klucz)


def test_odmowa_klingi_wraca_oknem_bez_recepty(strona, con, okno, recepty, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    ostrzezenia = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a: ostrzezenia.append(a[2])))

    def _odmowa(*a, **k):
        raise ValueError("klatka zniknęła")

    monkeypatch.setattr(repo, "set_frame_note", _odmowa)
    v = strona.frames_view
    _zaznacz(v, [1])
    okno.intencja = NoteIntent("set", "x")
    przed = len(recepty)
    v._on_notes()
    assert ostrzezenia == ["klatka zniknęła"] and len(recepty) == przed


def test_gest_uwag_w_Znajdz_przez_czasownik_paska(strona, con, okno):
    strona.show_find()
    v = strona.frames_view
    _zaznacz(v, [3])
    okno.intencja = NoteIntent("set", "Łuna")
    v.sel_bar.btn_notes.click()
    assert _uwagi(con) == {3: "Łuna"}
    wiersz = next(i for i, r in enumerate(v.model._rows) if r.get("frame_id") == 3)
    assert v.model.data(v.model.index(wiersz, v.model.base_col("note")), Qt.DisplayRole) == "Łuna"


def test_gest_wypychajacy_cel_z_widoku_mowi_to_i_odslania(strona, con, okno, statusy):
    repo.set_frame_note(con, frame_ids=[1, 2], body="x", now=NOW)
    v = strona.frames_view
    strona.show_find("uwagi:x")
    _zaznacz(v, [1])
    okno.intencja = NoteIntent("clear", None)
    v._on_notes()
    assert _ids(v) == [2]
    assert "poza widokiem: 1" in statusy[-1]


# ---------- przełączenie prezentacji przy otwartym edytorze komórki ----------

@pytest.fixture
def strona_z_plikami(qapp, tmp_path):
    """Dwie klatki z REALNYMI plikami FITS - edycja komórki keyworda trafia do szuflady tylko
    wtedy, gdy klinga celu widzi plik (wzorzec `test_gui_drogi_reki.wb_view`)."""
    import numpy as np
    from astropy.io import fits

    from horreum import scan
    from horreum.gui.flows.znajdz_view import ZnajdzView
    c = db.open_db(str(tmp_path / "wb.db"))
    for i in (1, 2):
        p = tmp_path / f"wb{i}.fits"
        hdu = fits.PrimaryHDU(data=np.full((4, 4), i, dtype=np.int16))
        hdu.header["TELESCOP"] = "RC8"
        hdu.header["IMAGETYP"] = "Light"
        hdu.writeto(str(p), overwrite=True)
        scan.ingest_record(c, scan.scan_file(str(p)), volume="V", now=NOW, summary=scan.ScanSummary())
    v = grid_mod.FramesView(c, now_fn=lambda: NOW)
    v._writeback_async = False
    s = ZnajdzView(v)
    yield s, c
    if not any(t.isRunning() for t in v.findChildren(QThread)):
        s.close()
        s.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    c.close()


def test_przelaczenie_przy_otwartym_edytorze_zatwierdza_wpis_i_zachowuje_zaznaczenie(
        strona_z_plikami):
    """Edytor otwarty prawdziwym klawiszem (F2) przy przełączeniu prezentacji: wpis trafia do
    szuflady (jak klik poza komórkę), a zaznaczenie przeżywa OSTATNIĄ przebudowę modelu - także
    tę od podglądu stagingu, która przychodzi w następnym obrocie pętli."""
    from PySide6.QtCore import QItemSelectionModel

    from horreum import writeback
    strona, c = strona_z_plikami
    v = strona.frames_view
    strona.resize(1400, 700)
    strona.show()
    strona.activateWindow()
    QTest.qWaitForWindowActive(strona)
    ids = sorted(r["frame_id"] for r in v.model._data_rows)
    _zaznacz(v, ids)
    m = v.model
    wiersz = next(i for i, r in enumerate(m._rows) if r.get("frame_id") == ids[0])
    idx = m.index(wiersz, m.n_bazowych() + m._kw_off() + m._keywords.index("TELESCOP"))
    v.table.selectionModel().setCurrentIndex(idx, QItemSelectionModel.NoUpdate)
    v.table.setFocus()
    QApplication.processEvents()
    QTest.keyClick(v.table, Qt.Key_F2)
    QApplication.processEvents()
    ed = v.table.indexWidget(idx)
    assert ed is not None and ed.wartosc.hasFocus(), "F2 nie otworzył edytora z fokusem"
    ed.wartosc.selectAll()
    QTest.keyClicks(ed.wartosc, "EQ6")
    strona.show_find()
    for _ in range(3):
        QApplication.processEvents()
    wpisy = writeback.pending_for_run(c, v._run_id)
    assert [(w["keyword"], w["new_value"]) for w in wpisy] == [("TELESCOP", "EQ6")]
    assert sorted(r["frame_id"] for r in v._selected_data_rows()) == ids, "zaznaczenie zginęło"


# ---------- chipy przy składzie w tle ----------

def _czekaj(warunek, limit_s=10.0):
    import time
    koniec = time.monotonic() + limit_s
    while not warunek():
        assert time.monotonic() < koniec, "skład w tle nie skończył w limicie"
        QApplication.processEvents()
        time.sleep(0.01)


def test_chipy_i_zdanie_mowia_o_PRZYLOZONYM_zbiorze_gdy_sklad_w_tle_trwa(qapp, con, monkeypatch):
    """Skład nowego zapytania wstrzymany w wątku tła: tabela pokazuje jeszcze zbiór poprzedniego.
    Chipy i zdanie „nie znam: …" nie mogą wtedy nazywać kryteriów nowego zapytania - także po
    przełączeniu prezentacji, które odbudowuje rząd chipów. Po przyłożeniu mówią o nowym.

    Falsyfikator: buduj chipy ze stanu intencji (`_facet_state`) → po przełączeniu prezentacji
    w trakcie składu rząd mówi „Filtr: Ha" nad klatkami M42."""
    import threading

    from horreum.gui.flows.znajdz_view import ZnajdzView
    wstrzymaj = threading.Event()
    wstrzymaj.set()
    prawdziwy = grid_mod._sklad_zbioru

    def _sklad(con_, stan, przerwij=lambda: None):
        wstrzymaj.wait(10)
        return prawdziwy(con_, stan, przerwij)

    monkeypatch.setattr(grid_mod, "_sklad_zbioru", _sklad)
    v = grid_mod.FramesView(con, now_fn=lambda: NOW, pola_poza_watkiem=True)
    s = ZnajdzView(v)
    try:
        _czekaj(lambda: not v.zbior_w_drodze() and v._pola_thread is None)
        s.show_find("m42")
        _czekaj(lambda: not v.zbior_w_drodze())
        widoczne = lambda: [c.text() for c in s._pula if c.isVisibleTo(s)]
        assert widoczne() == ["Obiekt: m42  ×"] and _ids(v) == [1, 2]

        wstrzymaj.clear()
        s.show_find("filtr:Ha foo:bar")
        QApplication.processEvents()
        assert v.zbior_w_drodze() and _ids(v) == [1, 2], "tabela dalej pokazuje M42"
        s.show_classic()
        s.show_find()
        assert widoczne() == ["Obiekt: m42  ×"], "chip nowego zapytania nad klatkami starego"
        assert not s.zdanie.isVisibleTo(s), "zdanie nowego zapytania przed jego zbiorem"

        wstrzymaj.set()
        _czekaj(lambda: not v.zbior_w_drodze())
        assert _ids(v) == [1, 3, 4]
        assert widoczne() == ["Filtr: Ha  ×"]
        assert s.zdanie.isVisibleTo(s) and "foo:bar" in s.zdanie.text()
    finally:
        wstrzymaj.set()
        v.zatrzymaj_pola()


def test_cofniecie_podaje_klindze_expected_z_migawki(strona, con, okno, recepty, monkeypatch):
    """Sprawdzenie zgodności w widoku jest prezentacją; prawdę rozstrzyga klinga pod blokadą,
    więc cofnięcie podaje jej `expected` = treść, którą zostawił gest (Z15)."""
    v = strona.frames_view
    _zaznacz(v, [1, 2])
    okno.intencja = NoteIntent("set", "x")
    v._on_notes()
    widziane = {}
    prawdziwa = repo.restore_frame_notes

    def _restore(con_, *, before, expected=None, now, uid="local"):
        widziane["expected"] = expected
        return prawdziwa(con_, before=before, expected=expected, now=now, uid=uid)

    monkeypatch.setattr(repo, "restore_frame_notes", _restore)
    recepty[-1].czlony[0].wykonaj()
    assert widziane["expected"] == {1: "x", 2: "x"}
    assert _uwagi(con) == {}


# ---------- pole zapytania wobec stanu, zapytanie bez trafień, start od „Przeglądu" ----------

def test_pole_czysci_sie_gdy_stan_zmieniono_spoza_pola(strona):
    """Pole nie udaje opisu stanu: po zdjęciu chipu (albo kliku w listwie, „× Wyczyść zbiór")
    zbiór nie jest już tym, który postawiło zapytanie - pole się czyści, stan mówią chipy."""
    v = strona.frames_view
    strona.show_find("filtr:Ha,OIII teleskop:rc8 foo:bar")
    assert strona.pole.text() == "filtr:Ha,OIII teleskop:rc8 foo:bar" and v.zapytanie_aktualne()
    assert strona.zdanie.isVisibleTo(strona)
    _chip(strona, "Filtr").click()
    assert strona.pole.text() == "" and not strona.zdanie.isVisibleTo(strona)
    assert _widoczne(strona) == ["Teleskop: rc8  ×"]

    strona.show_find("m42")
    v._on_facet_change({**v._facet_state, "filter": {"in": [["Ha", "Ha"]]}})
    assert strona.pole.text() == ""
    strona.show_find("m42")
    v.sel_bar.btn_clear.click()
    assert strona.pole.text() == ""


def test_pole_ktore_czlowiek_wlasnie_pisze_zostaje(strona):
    v = strona.frames_view
    strona.show_find("m42")
    strona.pole.setText("filtr:H")                          # nowe zapytanie w trakcie pisania
    v._on_facet_change({**v._facet_state, "filter": {"in": [["Ha", "Ha"]]}})
    assert strona.pole.text() == "filtr:H"


def test_zapytanie_bez_rozpoznanych_czesci_zostawia_zbior_i_mowi_to(strona):
    v = strona.frames_view
    strona.show_find("m42")
    gen = v._zbior_gen
    strona.show_find("bzdura:xyz")
    assert _ids(v) == [1, 2] and v._zbior_gen == gen, "zbiór zastąpiony całym archiwum"
    assert strona.zdanie.isVisibleTo(strona)
    assert strona.zdanie.text() == "Nie znam: bzdura:xyz - zbiór bez zmian."
    QTest.keyClicks(strona.pole, "a")                       # nowe pisanie zdejmuje zdanie
    assert not strona.zdanie.isVisibleTo(strona)


def test_zapytanie_bez_trafien_EN(strona):
    i18n.set_lang("en")
    strona.show_find("bzdura:xyz")
    assert strona.zdanie.text() == "Not recognised: bzdura:xyz - the set is unchanged."


def test_zapytanie_startuje_od_Przegladu_nie_dziedziczy_perspektywy(strona, monkeypatch):
    """Zapytanie po „Kalibracji" nie dziedziczy jej grupowania ani nazwy: etykieta „Przegląd"
    (zestaw i facety to zawężenie W RAMACH „Przeglądu"), bez grupowania, a manifest wydania
    dostaje „Przegląd", nie „Kalibracja (zmieniona)"."""
    v = strona.frames_view
    v.apply_perspective("Kalibracja")
    assert v.combo_group.currentData() == "kind"
    strona.show_find("zestaw:rc8_asi2600mm")
    assert _ids(v) == [1, 2, 4]
    assert v.combo_persp.currentData() == ("preset", grid_mod._PRESET_CZYSTY)
    assert v.combo_persp.currentText() == i18n.t("perspective.review")
    assert v.combo_group.currentData() is None and v.model._group_by is None
    widziane = {}

    class _Dialog:
        summary = None

        def __init__(self, *a, perspektywa=None, **k):
            widziane["perspektywa"] = perspektywa

        def exec(self):
            return 0

    monkeypatch.setattr(grid_mod, "ProjectionDialog", _Dialog)
    v._open_projection()
    assert widziane["perspektywa"] == i18n.t("perspective.review")


def test_wydaj_do_WBPP_przy_skladzie_w_tle_otwiera_teczki_bez_podpowiedzi(qapp, con, monkeypatch):
    """Skład wstrzymany w wątku tła: „Wydaj do WBPP" (pasek i kafel Domu) nie odmawia zdaniem
    o tabeli - okno teczek otwiera się bez preselekcji, bo podpowiedź ze zbioru, który zaraz
    zniknie, wskazałaby cudzą teczkę. Po przyłożeniu podpowiedź wraca."""
    import threading

    from horreum.gui.flows.znajdz_view import ZnajdzView
    wstrzymaj = threading.Event()
    wstrzymaj.set()
    prawdziwy = grid_mod._sklad_zbioru

    def _sklad(con_, stan, przerwij=lambda: None):
        wstrzymaj.wait(10)
        return prawdziwy(con_, stan, przerwij)

    otwarte = []

    class _Teczki:
        def __init__(self, con_, *, preselect=None, parent=None):
            otwarte.append(preselect)

        def exec(self):
            return 0

    monkeypatch.setattr(grid_mod, "_sklad_zbioru", _sklad)
    monkeypatch.setattr(grid_mod, "ObjectPickDialog", _Teczki)
    v = grid_mod.FramesView(con, now_fn=lambda: NOW, pola_poza_watkiem=True)
    s = ZnajdzView(v)
    statusy = []
    v.status_message.connect(statusy.append)
    try:
        _czekaj(lambda: not v.zbior_w_drodze() and v._pola_thread is None)
        s.show_find("m42")
        _czekaj(lambda: not v.zbior_w_drodze())
        v.sel_bar.btn_obj.click()
        assert otwarte == [1]
        wstrzymaj.clear()
        s.show_find("lmc")
        QApplication.processEvents()
        assert v.zbior_w_drodze()
        v._open_object_release()
        assert otwarte == [1, None]
        assert i18n.t("grid.sel.loading_refused") not in statusy
    finally:
        wstrzymaj.set()
        v.zatrzymaj_pola()
