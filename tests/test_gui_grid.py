"""Widok „Klatki" (PLAN_gui_grid) — testy STERUJĄCE realnym oknem Qt (offscreen). Model 3 stanów +
sort + grupowanie; FilterPanel → drzewo; FramesView refresh/filtr/perspektywa. `importorskip` na poziomie
modułu (§9.4): bez PySide6 plik się POMIJA (pełny pytest bez Qt zostaje prawdziwy)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from horreum import db, pivot as pivot_mod, writeback
from horreum.gui import queries

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

NOW = "2026-07-03T14:00:00"


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


def _seed(con):
    """Ta sama zawartość co test_grid_core: 4 frame'y (f3=XISF bez cards, f4 zniknięta, f1 duplikat)."""
    con.executemany(
        "INSERT INTO frame (id, sha1_data, kind, filetype, first_seen_at) VALUES (?,?,?,?,?)",
        [(1, "d1", "light", "fits", NOW), (2, "d2", "light", "fits", NOW),
         (3, "d3", "master_flat", "xisf", NOW), (4, "d4", "light", "fits", NOW)],
    )
    con.executemany(
        "INSERT INTO cards (frame_id, keyword, idx, value_raw, value_num, value_type) VALUES (?,?,?,?,?,?)",
        [(1, "OBJECT", 0, "M51", None, "str"), (1, "EXPTIME", 0, "300", 300.0, "float"),
         (1, "GAIN", 0, "100", 100.0, "int"),
         (2, "OBJECT", 0, "NGC891", None, "str"), (2, "EXPTIME", 0, "60", 60.0, "float"),
         (2, "GAIN", 0, "100", 100.0, "int"),
         (4, "OBJECT", 0, "M51", None, "str"), (4, "EXPTIME", 0, "120", 120.0, "float")],
    )
    con.executemany(
        "INSERT INTO location (frame_id, volume, path, present) VALUES (?,?,?,?)",
        [(1, "V", "/a/f1.fits", 1), (1, "V", "/b/f1c.fits", 1), (2, "V", "/a/f2.fits", 1),
         (3, "V", "/a/f3.xisf", 1), (4, "V", "/a/f4.fits", 0)],
    )
    con.executemany(
        "INSERT INTO header (frame_id, raw_json, object_raw, exptime) VALUES (?,?,?,?)",
        [(1, "{}", "M51", 300.0), (2, "{}", "NGC891", 60.0), (4, "{}", "M51", 120.0)],
    )
    con.commit()


@pytest.fixture
def gcon(tmp_path):
    con = db.open_db(str(tmp_path / "g.db"))
    _seed(con)
    yield con
    con.close()


@pytest.fixture
def view(qapp, gcon, tmp_path, monkeypatch):
    # Izolacja QSettings (perspektywy) — nie dotykaj realnego rejestru użytkownika.
    from PySide6.QtCore import QSettings
    monkeypatch.setattr(QSettings, "value", lambda self, k, d=None: d)
    monkeypatch.setattr(QSettings, "setValue", lambda self, k, v: None)
    from horreum.gui.grid import FramesView
    v = FramesView(gcon, now_fn=None)
    v._writeback_async = False   # test: worker.run() inline (sync-seam), bez QThread
    yield v


# ---------- model ----------

def test_model_kształt_i_stany(gcon):
    from horreum.gui.grid import GridTableModel, BASE_COLS
    base = [{"frame_id": 1, "path": "/a/f1.fits", "kind": "light", "camera_model": None,
             "telescope_label": None, "telescop_canon": "RC8", "object_canon": None, "object_raw": "M51",
             "filter_canon": None, "present": 1, "n_present": 2,
             "_telescope": "RC8", "_object": "M51"}]
    rows = queries.cards_pivot(gcon, [1], ["OBJECT", "GAIN", "FOO"])
    pv = pivot_mod.build_pivot([1], ["OBJECT", "GAIN", "FOO"], rows)
    m = GridTableModel()
    m.set_data(base, pv, ["OBJECT", "GAIN", "FOO"])
    assert m.columnCount() == len(BASE_COLS) + 3
    assert m.rowCount() == 1
    # kolumna keyworda OBJECT (idx = len(BASE_COLS)) → wartość
    idx_obj = m.index(0, len(BASE_COLS))
    assert m.data(idx_obj, Qt.DisplayRole) == "M51"
    # FOO nie istnieje → MISSING em-dash + kursywa
    idx_foo = m.index(0, len(BASE_COLS) + 2)
    assert m.data(idx_foo, Qt.DisplayRole) == "—"
    assert m.data(idx_foo, Qt.FontRole).italic()
    # GAIN numeryczny → wyrównanie do prawej
    idx_gain = m.index(0, len(BASE_COLS) + 1)
    assert m.data(idx_gain, Qt.TextAlignmentRole) == int(Qt.AlignRight | Qt.AlignVCenter)


def test_model_sort_missing_na_koncu(gcon):
    from horreum.gui.grid import GridTableModel, BASE_COLS
    base = [
        {"frame_id": 1, "path": "a", "_telescope": "", "_object": "", "kind": "light",
         "camera_model": None, "filter_canon": None, "present": 1, "n_present": 1},
        {"frame_id": 3, "path": "c", "_telescope": "", "_object": "", "kind": "flat",
         "camera_model": None, "filter_canon": None, "present": 1, "n_present": 1},
    ]
    rows = queries.cards_pivot(gcon, [1, 3], ["EXPTIME"])
    pv = pivot_mod.build_pivot([1, 3], ["EXPTIME"], rows)
    m = GridTableModel(); m.set_data(base, pv, ["EXPTIME"])
    col = len(BASE_COLS)
    m.sort(col, Qt.AscendingOrder)   # f3 nie ma EXPTIME → MISSING na końcu
    assert m._rows[-1]["frame_id"] == 3
    m.sort(col, Qt.DescendingOrder)  # nawet malejąco MISSING zostaje na końcu
    assert m._rows[-1]["frame_id"] == 3


def test_model_grupowanie_naglowki(gcon):
    from horreum.gui.grid import GridTableModel
    base = [
        {"frame_id": 1, "path": "a", "kind": "light", "_telescope": "", "_object": "",
         "camera_model": None, "filter_canon": None, "present": 1, "n_present": 1},
        {"frame_id": 2, "path": "b", "kind": "light", "_telescope": "", "_object": "",
         "camera_model": None, "filter_canon": None, "present": 1, "n_present": 1},
        {"frame_id": 3, "path": "c", "kind": "master_flat", "_telescope": "", "_object": "",
         "camera_model": None, "filter_canon": None, "present": 1, "n_present": 1},
    ]
    m = GridTableModel()
    m.set_data(base, pivot_mod.build_pivot([1, 2, 3], [], []), [], group_by="kind")
    groups = [r for r in m._rows if "_group" in r]
    assert {g["_group"] for g in groups} == {"light", "master_flat"}
    light = next(g for g in groups if g["_group"] == "light")
    assert light["_count"] == 2


# ---------- FilterPanel ----------

def test_filterpanel_buduje_drzewo(qapp):
    from horreum.gui.grid import FilterPanel
    p = FilterPanel(["OBJECT", "GAIN"])
    p.add_row(); p.add_row()
    p._rows[0]["kw"].setCurrentText("OBJECT"); p._rows[0]["op"].setCurrentIndex(0)  # eq
    p._rows[0]["val"].setText("M51")
    p._rows[1]["kw"].setCurrentText("GAIN"); p._rows[1]["op"].setCurrentIndex(0)
    p._rows[1]["val"].setText("100")
    tree = p.build_tree()
    assert tree["op"] == "AND"
    assert {c["keyword"] for c in tree["conditions"]} == {"OBJECT", "GAIN"}


def test_filterpanel_pusty_to_none(qapp):
    from horreum.gui.grid import FilterPanel
    p = FilterPanel(["OBJECT"])
    assert p.build_tree() is None


def test_filterpanel_niedokonczony_wiersz_pomijany(qapp):
    """Domyślny/edytowalny wiersz auto-wybiera keyword — bez wartości NIE może wstrzyknąć `eq ''`
    (inaczej zawęża wynik do zera). Tylko wiersz z wartością lub operatorem bez-wartości liczy się."""
    from horreum.gui.grid import FilterPanel
    p = FilterPanel(["GAIN", "OBJECT"])          # domyślny wiersz: kw='GAIN', op=eq, wartość pusta
    p.add_row()                                   # drugi też pusty
    p._rows[0]["kw"].setCurrentText("OBJECT"); p._rows[0]["op"].setCurrentIndex(0)  # eq, wartość pusta
    assert p.build_tree() is None                 # oba niedokończone → brak filtra
    # operator bez-wartości (exists) liczy się mimo pustego pola
    p._rows[1]["kw"].setCurrentText("GAIN"); p._rows[1]["op"].setCurrentIndex(8)  # 'istnieje'
    tree = p.build_tree()
    assert tree["conditions"] == [{"keyword": "GAIN", "operator": "exists"}]


def test_filterpanel_set_tree_odbija_preset(qapp):
    """set_tree odtwarza jednopoziomową grupę (P3-3: panel = filtr perspektywy, nie druga instancja)."""
    from horreum.gui.grid import FilterPanel
    p = FilterPanel(["IMAGETYP"])
    tree = {"op": "OR", "conditions": [
        {"keyword": "IMAGETYP", "operator": "contains", "value": "dark"},
        {"keyword": "IMAGETYP", "operator": "contains", "value": "flat"},
    ]}
    p.set_tree(tree)
    assert p.build_tree() == tree                 # round-trip: co odtworzone, to odczytane


def test_filterpanel_odwroc_owija_w_not(qapp):
    """Checkbox „Odwróć" owija zbudowane drzewo w NOT (F1)."""
    from horreum.gui.grid import FilterPanel
    p = FilterPanel(["OBJECT"])
    p._rows[0]["kw"].setCurrentText("OBJECT"); p._rows[0]["op"].setCurrentIndex(0)  # eq
    p._rows[0]["val"].setText("M51")
    p.chk_invert.setChecked(True)
    tree = p.build_tree()
    assert tree["op"] == "NOT"
    assert len(tree["conditions"]) == 1
    assert tree["conditions"][0]["conditions"][0]["keyword"] == "OBJECT"


def test_filterpanel_pusty_z_odwroc_to_none(qapp):
    """Pusty panel + zaznaczony „Odwróć" → None (uniwersum), BEZ owijania — UI nie kłamie ∅-em."""
    from horreum.gui.grid import FilterPanel
    p = FilterPanel(["OBJECT"])
    p.chk_invert.setChecked(True)
    assert p.build_tree() is None


def test_filterpanel_set_tree_rozpoznaje_not(qapp):
    """set_tree z korzeniem NOT: checkbox zaznaczony + dziecko odtworzone płasko; round-trip przeżywa
    (R#1 BLOKUJĄCE: bez tego perspektywa z NOT wczytuje się w pusty panel i „Zastosuj" kasuje negację)."""
    from horreum.gui.grid import FilterPanel
    p = FilterPanel(["IMAGETYP"])
    tree = {"op": "NOT", "conditions": [{"op": "AND", "conditions": [
        {"keyword": "IMAGETYP", "operator": "contains", "value": "dark"},
    ]}]}
    p.set_tree(tree)
    assert p.chk_invert.isChecked()
    assert p.build_tree() == tree                 # round-trip: negacja przeżywa „Zastosuj"


def test_filterpanel_set_tree_zwykly_odznacza_odwroc(qapp):
    """set_tree bez NOT odznacza checkbox — stan panelu zawsze odbija wczytany filtr."""
    from horreum.gui.grid import FilterPanel
    p = FilterPanel(["OBJECT"])
    p.chk_invert.setChecked(True)
    p.set_tree({"op": "AND", "conditions": [{"keyword": "OBJECT", "operator": "exists"}]})
    assert not p.chk_invert.isChecked()
    p.chk_invert.setChecked(True)
    p.set_tree(None)
    assert not p.chk_invert.isChecked()


# ---------- FramesView (integracja) ----------

def test_view_refresh_liczy_klatki(view):
    assert view.count_label.text() == "4 klatek"
    assert view.model.rowCount() >= 4  # 4 klatki (+ ewentualne nagłówki grup, tu brak)


def test_view_filtr_gain(view):
    view.filter_panel.add_row()
    view.filter_panel._rows[0]["kw"].setCurrentText("GAIN")
    view.filter_panel._rows[0]["op"].setCurrentIndex(0)  # eq
    view.filter_panel._rows[0]["val"].setText("100")
    view.filter_panel._apply()
    assert view.count_label.text() == "2 klatek"  # f1,f2


def test_view_filtr_odwrocony(view):
    """GAIN=100 odwrócony → uniwersum − {f1,f2} = {f3,f4} (XISF bez cards wchodzi przez uniwersum)."""
    view.filter_panel.add_row()
    view.filter_panel._rows[0]["kw"].setCurrentText("GAIN")
    view.filter_panel._rows[0]["op"].setCurrentIndex(0)  # eq
    view.filter_panel._rows[0]["val"].setText("100")
    view.filter_panel.chk_invert.setChecked(True)
    view.filter_panel._apply()
    assert view.count_label.text() == "2 klatek"


def test_view_perspektywa_z_not_przezywa_zastosuj(view):
    """Round-trip R#1: filtr perspektywy z korzeniem NOT → panel go odbija → „Zastosuj" NIE kasuje
    negacji (scenariusz P3-3 piętro wyżej: bez poprawki set_tree pierwszy Zastosuj gubił NOT)."""
    tree = {"op": "NOT", "conditions": [{"op": "AND", "conditions": [
        {"keyword": "GAIN", "operator": "eq", "value": "100"},
    ]}]}
    view._filter_tree = tree
    view.filter_panel.set_tree(tree)      # ścieżka _on_perspective (P3-3)
    view.refresh()
    assert view.count_label.text() == "2 klatek"
    view.filter_panel._apply()            # user klika „Zastosuj" bez zmian
    assert view._filter_tree == tree      # negacja przeżywa
    assert view.count_label.text() == "2 klatek"


def test_view_perspektywa_duplikaty(view):
    idx = view.combo_persp.findText("Duplikaty")
    view.combo_persp.setCurrentIndex(idx)
    assert view.count_label.text() == "1 klatek"  # tylko f1 (n_present=2)


def test_view_grupowanie(view):
    idx = view.combo_group.findData("kind")
    view.combo_group.setCurrentIndex(idx)
    groups = [r for r in view.model._rows if "_group" in r]
    assert {g["_group"] for g in groups} == {"light", "master_flat"}


# ---------- FramesView: listwa facetów (F4 — PLAN_ux_redesign §5) ----------
# Seed bez obiektów/configów/nocy → wehikułem testów jest facet Rodzaj (light×3, master_flat×1).

def _rail_item(view, facet, value):
    """Wiersz listwy dla wartości facetu (po danych UserRole, nie tekście — tekst niesie ✓/⊖/n)."""
    lw = view.facet_rail._lists[facet]
    for i in range(lw.count()):
        it = lw.item(i)
        if it.data(Qt.UserRole)[1] == value:
            return it
    raise AssertionError(f"brak wartości {value!r} w facecie {facet}")


def test_facet_klik_cykluje_none_in_ex_none(view):
    """Cykl kliku (F4): zawęź → wyklucz → zdejmij, zbiór odbija każdy krok (`itemClicked` handler)."""
    view.facet_rail._on_item_clicked(_rail_item(view, "kind", "light"))
    assert view._facet_state == {"kind": {"in": [["light", "light"]]}}
    assert view.count_label.text() == "3 klatek"                    # f1,f2,f4
    view.facet_rail._on_item_clicked(_rail_item(view, "kind", "light"))
    assert view._facet_state == {"kind": {"ex": [["light", "light"]]}}
    assert view.count_label.text() == "1 klatek"                    # uniwersum − lighty = f3
    view.facet_rail._on_item_clicked(_rail_item(view, "kind", "light"))
    assert view._facet_state == {}
    assert view.count_label.text() == "4 klatek"


def test_facet_sibling_lista_pokazuje_sasiadow(view):
    """F4R#1: po zawężeniu do light lista Rodzaju NADAL pokazuje master_flat (sibling-set — inaczej
    OR-wewnątrz byłby nieosiągalny); aktywna wartość znaczona ✓."""
    view.facet_rail._on_item_clicked(_rail_item(view, "kind", "light"))
    lw = view.facet_rail._lists["kind"]
    values = {lw.item(i).data(Qt.UserRole)[1] for i in range(lw.count())}
    assert values == {"light", "master_flat"}
    assert _rail_item(view, "kind", "light").text().startswith("✓ ")
    assert _rail_item(view, "kind", "master_flat").text() == "master_flat (1)"


def test_facet_ex_render_ukryte(view):
    """F4R2#1: „(n)" przy ⊖ znaczy „ile wróci po zdjęciu" — render to nazywa, nie udaje wkładu."""
    view.facet_rail._on_item_clicked(_rail_item(view, "kind", "light"))
    view.facet_rail._on_item_clicked(_rail_item(view, "kind", "light"))   # in → ex
    assert _rail_item(view, "kind", "light").text() == "⊖ light (+3 ukryte)"


def test_facet_pin_aktywnego_poza_siblingiem(view):
    """Aktywny wybór ZAWSZE renderowany: ⊖ master_flat + advanced GAIN-istnieje odcina master_flat
    z sibling-setu (XISF bez cards) → wiersz zostaje PINowany (niewidzialny filtr = UI kłamie)."""
    view.facet_rail._on_item_clicked(_rail_item(view, "kind", "master_flat"))
    view.facet_rail._on_item_clicked(_rail_item(view, "kind", "master_flat"))  # in → ex
    view.filter_panel.add_row()
    view.filter_panel._rows[0]["kw"].setCurrentText("GAIN")
    view.filter_panel._rows[0]["op"].setCurrentIndex(8)   # 'istnieje'
    view.filter_panel._apply()
    assert view.count_label.text() == "2 klatek"          # f1,f2 (GAIN) − master_flat i tak poza
    assert _rail_item(view, "kind", "master_flat").text() == "⊖ master_flat (+0 ukryte)"


def test_facet_kryteria_paska(view):
    """F4R#8: pasek zbioru opisuje drzewo EFEKTYWNE — facet wchodzi w kryteria słowami."""
    view.facet_rail._on_item_clicked(_rail_item(view, "kind", "light"))
    assert "Rodzaj: light" in view.sel_bar.criteria_label._full


def test_facet_rail_zachowuje_scroll_po_przeladowaniu(qapp):
    """Firsthand F4: klik wartości w środku długiej listy przeładowuje listwę (`set_data`) —
    pozycja scrolla MUSI przeżyć (inaczej widok ucieka na górę i user szuka wartości od nowa)."""
    from horreum.gui.facets import FacetRail
    rail = FacetRail()
    rail.resize(260, 500)
    rail.show()
    counts = {"object": [(i, f"OBJ{i:03d}", 1) for i in range(60)],
              "filter": [], "kind": [], "telescope": [], "night": []}
    rail.set_data(counts, {})
    qapp.processEvents()
    lw = rail._lists["object"]
    bar = lw.verticalScrollBar()
    bar.setValue(bar.maximum())
    pos = bar.value()
    assert pos > 0                                        # lista realnie przescrollowana
    rail.set_data(counts, {"object": {"in": [[40, "OBJ040"]]}})   # przeładowanie jak po kliku
    assert bar.value() == pos
    rail.hide()


def test_facet_wyczysc_zbior(view):
    """Wiz F4 #3: „× Wyczyść zbiór" zdejmuje facety + advanced JEDNYM klikiem; uczciwy disabled,
    gdy nie ma co zdjąć (preset „Przegląd" jest no-opem, gdy już wybrany — to była jedyna droga)."""
    assert not view.sel_bar.btn_clear.isEnabled()          # nic do czyszczenia
    view.facet_rail._on_item_clicked(_rail_item(view, "kind", "light"))
    view.filter_panel._rows[0]["kw"].setCurrentText("GAIN")
    view.filter_panel._rows[0]["op"].setCurrentIndex(8)    # 'istnieje'
    view.filter_panel._apply()
    assert view.count_label.text() == "2 klatek"           # lighty ∩ GAIN
    assert view.sel_bar.btn_clear.isEnabled()
    view.sel_bar.btn_clear.click()
    assert view._facet_state == {} and view._filter_tree is None
    assert view.count_label.text() == "4 klatek"
    assert not view.sel_bar.btn_clear.isEnabled()


def test_facet_preset_zeruje_stan(view):
    """F4R#2: perspektywa definiuje CAŁY zbiór — wczytanie presetu bez `facets` zdejmuje facety."""
    view.facet_rail._on_item_clicked(_rail_item(view, "kind", "light"))
    assert view._facet_state
    idx = view.combo_persp.findText("Przegląd")
    view.combo_persp.setCurrentIndex(idx) if idx != view.combo_persp.currentIndex() else view._on_perspective()
    assert view._facet_state == {}
    assert view.count_label.text() == "4 klatek"


@pytest.fixture
def view_settings(qapp, gcon, monkeypatch):
    """FramesView z QSettings na SŁOWNIKU (round-trip perspektyw wymaga realnego zapisu/odczytu,
    nie no-op jak w `view`; nadal zero dotykania rejestru usera)."""
    from PySide6.QtCore import QSettings
    store = {}
    monkeypatch.setattr(QSettings, "value", lambda self, k, d=None: store.get(k, d))
    monkeypatch.setattr(QSettings, "setValue", lambda self, k, v: store.__setitem__(k, v))
    from horreum.gui.grid import FramesView
    v = FramesView(gcon, now_fn=None)
    v._writeback_async = False
    yield v


def test_facet_roundtrip_perspektywy_zlozonej(view_settings, monkeypatch):
    """Round-trip perspektywy ZŁOŻONEJ (nota R2): facety→rail, advanced→panel; combo odbija zapis
    (F4R2#6); „Zastosuj" panelu NIE kasuje facetów; stara perspektywa nadpisuje stan w całości."""
    from PySide6.QtWidgets import QInputDialog
    v = view_settings
    v.facet_rail._on_item_clicked(_rail_item(v, "kind", "light"))
    v._filter_tree = {"keyword": "GAIN", "operator": "exists"}
    v.filter_panel.set_tree(v._filter_tree)
    v.refresh()
    assert v.count_label.text() == "2 klatek"             # lighty ∩ GAIN = f1,f2
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Zlozona", True)))
    v._save_perspective()
    assert v.combo_persp.currentData() == ("saved", "Zlozona")   # F4R2#6: etykieta nie kłamie
    # odejdź na preset (F4R#2: preset zeruje facety)…
    v.combo_persp.setCurrentIndex(v.combo_persp.findText("Przegląd"))
    assert v._facet_state == {}
    assert v.count_label.text() == "4 klatek"
    # …i wróć do zapisanej: facety wracają do raila, advanced do panelu
    for i in range(v.combo_persp.count()):
        if v.combo_persp.itemData(i) == ("saved", "Zlozona"):
            v.combo_persp.setCurrentIndex(i)
            break
    assert v._facet_state == {"kind": {"in": [["light", "light"]]}}
    assert v.count_label.text() == "2 klatek"
    assert _rail_item(v, "kind", "light").text().startswith("✓ ")
    v.filter_panel._apply()                               # „Zastosuj" panelu — facety przeżywają
    assert v._facet_state == {"kind": {"in": [["light", "light"]]}}
    assert v.count_label.text() == "2 klatek"


# ---------- FramesView: makro / writeback (KROK 4) ----------

@pytest.fixture
def wb_view(qapp, tmp_path, monkeypatch):
    """FramesView nad bazą z JEDNYM realnym plikiem FITS (writeback rusza dysk — potrzebny prawdziwy)."""
    import numpy as np
    from astropy.io import fits
    from PySide6.QtCore import QSettings
    from horreum import scan
    from horreum.gui.grid import FramesView
    monkeypatch.setattr(QSettings, "value", lambda self, k, d=None: d)
    monkeypatch.setattr(QSettings, "setValue", lambda self, k, v: None)
    p = tmp_path / "wb.fits"
    hdu = fits.PrimaryHDU(data=np.zeros((4, 4), dtype=np.int16))
    hdu.header["TELESCOP"] = "RC8"; hdu.header["IMAGETYP"] = "Light"
    hdu.writeto(str(p), overwrite=True)
    con = db.open_db(str(tmp_path / "wb.db"))
    scan.ingest_record(con, scan.scan_file(str(p)), volume="V", now=NOW, summary=scan.ScanSummary())
    v = FramesView(con, now_fn=lambda: NOW)
    v._writeback_async = False   # test: worker.run() inline (sygnały direct = synchronicznie), bez QThread
    yield v, con, p
    con.close()


def test_macro_preview_populates_column(wb_view):
    view, con, p = wb_view
    view.macro_bar.asg_kw.setCurrentText("TELESCOP")
    view.macro_bar.asg_op.setCurrentIndex(0)  # set
    view.macro_bar.asg_expr.setText("SkyWatcher RC8")
    view.macro_bar._emit_preview()
    # kolumna „makro →" dołożona, komórka = stara→nowa
    from horreum.gui.grid import BASE_COLS
    pcol = len(BASE_COLS) + len(view._columns)
    assert view.model.columnCount() == pcol + 1
    txt = view.model.data(view.model.index(0, pcol), Qt.DisplayRole)
    assert txt == "RC8 → SkyWatcher RC8"
    # wizytator #1/#2: dotknięty wiersz ma TŁO w kolumnach bazowych (widoczne bez scrolla)
    bg = view.model.data(view.model.index(0, 0), Qt.BackgroundRole)
    from horreum.gui.grid import _TOUCHED_BG
    assert bg == _TOUCHED_BG
    # podgląd NIE zapisuje: staging pusty
    assert view._pending_count() == 0


def test_macro_stage_then_commit_edits_file(wb_view):
    view, con, p = wb_view
    from astropy.io import fits
    view.macro_bar.asg_kw.setCurrentText("TELESCOP")
    view.macro_bar.asg_op.setCurrentIndex(0)
    view.macro_bar.asg_expr.setText("EQ6")
    view.macro_bar._emit_stage()
    assert view._pending_count() == 1 and view.drawer._n == 1

    view._on_commit()
    assert fits.getheader(str(p))["TELESCOP"] == "EQ6"   # plik zmieniony
    assert view._run_id is None                          # run domknięty (R#5)
    assert view._pending_count() == 0
    assert hasattr(view, "_last_commit_id")

    # cofnij przez szufladę
    view._on_undo(view._last_commit_id)
    assert fits.getheader(str(p))["TELESCOP"] == "RC8"   # przywrócone


def test_macro_reject_clears_staging(wb_view):
    view, con, p = wb_view
    view.macro_bar.asg_kw.setCurrentText("TELESCOP")
    view.macro_bar.asg_op.setCurrentIndex(0)
    view.macro_bar.asg_expr.setText("EQ6")
    view.macro_bar._emit_stage()
    assert view._pending_count() == 1
    view._on_reject()
    assert view._run_id is None and view._pending_count() == 0
    assert view.model._preview == {}


def test_writeback_worker_commit_emituje_postep(wb_view):
    """Worker off-thread (pipeline-konwencja: test przez bezpośrednie run()) woła rdzeń z progresem,
    zwraca `done(op, CommitResult)` i zapisuje plik przez WŁASNE połączenie."""
    view, con, p = wb_view
    from astropy.io import fits
    from horreum.gui.grid import WritebackWorker
    view.macro_bar.asg_kw.setCurrentText("TELESCOP"); view.macro_bar.asg_op.setCurrentIndex(0)
    view.macro_bar.asg_expr.setText("EQ6"); view.macro_bar._emit_stage()
    w = WritebackWorker(view._db_path, "commit", view._run_id, now_fn=lambda: NOW)
    prog, done = [], []
    w.progress.connect(lambda d, t, path, s: prog.append((d, t)))
    w.done.connect(lambda op, res: done.append((op, res)))
    w.run()
    assert prog and prog[-1][0] == prog[-1][1]              # postęp doszedł do total/total (100%)
    assert done and done[0][0] == "commit" and len(done[0][1].applied) == 1
    assert fits.getheader(str(p))["TELESCOP"] == "EQ6"      # plik zapisany PRZEZ worker


def test_writeback_worker_anulowanie_zostawia_pending(wb_view):
    """should_cancel wpięty: anulowanie PRZED plikiem zostawia pending nietknięte (czysty stan do dokończenia)."""
    view, con, p = wb_view
    from astropy.io import fits
    from horreum.gui.grid import WritebackWorker
    view.macro_bar.asg_kw.setCurrentText("TELESCOP"); view.macro_bar.asg_op.setCurrentIndex(0)
    view.macro_bar.asg_expr.setText("EQ6"); view.macro_bar._emit_stage()
    w = WritebackWorker(view._db_path, "commit", view._run_id, now_fn=lambda: NOW)
    w.request_cancel()
    done = []
    w.done.connect(lambda op, res: done.append(res))
    w.run()
    assert done and len(done[0].applied) == 0              # nic nie zapisane
    assert fits.getheader(str(p))["TELESCOP"] == "RC8"     # plik nietknięty
    assert view._pending_count() == 1                      # pending zostaje → dokończalne


# ---------- kolumna Δh + sort/grupowanie (PLAN_wejscia_nazw §1) ----------

def _delta_row(fid, delta):
    return {"frame_id": fid, "path": chr(96 + fid), "_telescope": "", "_object": "", "kind": "light",
            "camera_model": None, "filter_canon": None, "present": 1, "n_present": 1, "_dt_delta": delta}


def test_dt_delta_kolumna_display_i_sort(gcon):
    """R2 #3: JEDEN typ float — pełna godzina „-2", ułamek „-1.97", None → pusto. R1 #6: sort numeryczny,
    None na koniec w OBU kierunkach."""
    from horreum.gui.grid import GridTableModel, BASE_COLS
    dcol = [k for _, k in BASE_COLS].index("_dt_delta")
    base = [_delta_row(1, -2.0), _delta_row(2, -1.97), _delta_row(3, None)]
    m = GridTableModel(); m.set_data(base, pivot_mod.build_pivot([1, 2, 3], [], []), [])

    def disp(fid):
        r = next(i for i, row in enumerate(m._rows) if row.get("frame_id") == fid)
        return m.data(m.index(r, dcol), Qt.DisplayRole)
    assert disp(1) == "-2" and disp(2) == "-1.97" and disp(3) == ""
    # prawy align (kolumna liczbowa), None bez align
    assert m.data(m.index(0, dcol), Qt.TextAlignmentRole) is not None

    m.sort(dcol, Qt.AscendingOrder)
    assert [r["frame_id"] for r in m._rows if "frame_id" in r] == [1, 2, 3]   # -2, -1.97, None-koniec
    m.sort(dcol, Qt.DescendingOrder)
    assert [r["frame_id"] for r in m._rows if "frame_id" in r] == [2, 1, 3]   # -1.97, -2, None-koniec


def test_dt_delta_grupy_porzadek_numeryczny(gcon):
    """R2 #4: nagłówki grup Δh w porządku NUMERYCZNYM (-12, -2, -1), nie tekstowym (-1, -12, -2)."""
    from horreum.gui.grid import GridTableModel
    base = [_delta_row(1, -2.0), _delta_row(2, -12.0), _delta_row(3, -1.0)]
    m = GridTableModel()
    m.set_data(base, pivot_mod.build_pivot([1, 2, 3], [], []), [], group_by="_dt_delta")
    assert [r["_group"] for r in m._rows if "_group" in r] == ["-12", "-2", "-1"]


# ---------- RenameBar: znak align zależny od źródła + half-away (§1, R2 #2/#5) ----------

def test_renamebar_align_znak_zalezny_od_zrodla(qapp):
    from horreum.gui.grid import RenameBar
    bar = RenameBar()
    bar.src.setCurrentIndex(0)                       # date_obs → offset = −median
    bar.set_echo("", "", "", "", median=-2.0)
    bar._align(); assert bar.offset.value() == 2
    bar.src.setCurrentIndex(1)                       # filename → offset = +median
    bar.set_echo("", "", "", "", median=-2.0)
    bar._align(); assert bar.offset.value() == -2


def test_renamebar_half_away_nie_half_to_even(qapp):
    """R2 #5: -2.5 → -3 (half-away-from-zero), NIE -2 (goły round() = half-to-even)."""
    from horreum.gui.grid import RenameBar, _half_away
    assert _half_away(-2.5) == -3 and _half_away(2.5) == 3 and _half_away(-1.97) == -2
    bar = RenameBar(); bar.src.setCurrentIndex(1)    # filename → signed = median
    bar.set_echo("", "", "", "", median=-2.5)
    bar._align(); assert bar.offset.value() == -3


# ---------- FramesView: rename — cykl życia run_id / mutex / dispatch / podgląd (§1, R1/R2) ----------

@pytest.fixture
def rn_view(qapp, tmp_path, monkeypatch):
    """FramesView nad bazą z DWOMA realnymi FITS (różne DANE → różne frame'y; DATE-OBS+TELESCOP dla
    renamu I makra). Rename rusza dysk — pliki w tmp_path, NIGDY R:."""
    import numpy as np
    from astropy.io import fits
    from PySide6.QtCore import QSettings
    from horreum import scan
    from horreum.gui.grid import FramesView
    monkeypatch.setattr(QSettings, "value", lambda self, k, d=None: d)
    monkeypatch.setattr(QSettings, "setValue", lambda self, k, v: None)
    con = db.open_db(str(tmp_path / "rn.db"))
    files = []
    for i, (obj, dobs) in enumerate([("NGC7000", "2024-03-15T21:30:45"),
                                     ("M42", "2024-03-16T22:00:00")]):
        p = tmp_path / f"raw{i}.fits"
        hdu = fits.PrimaryHDU(data=np.full((4, 4), i + 1, dtype=np.int16))
        hdu.header["IMAGETYP"] = "Light"; hdu.header["OBJECT"] = obj; hdu.header["TELESCOP"] = "RC8"
        hdu.header["FILTER"] = "Ha"; hdu.header["DATE-OBS"] = dobs; hdu.header["EXPTIME"] = 300.0
        hdu.writeto(str(p), overwrite=True)
        scan.ingest_record(con, scan.scan_file(str(p)), volume="V", now=NOW, summary=scan.ScanSummary())
        files.append(p)
    v = FramesView(con, now_fn=lambda: NOW)
    v._writeback_async = False   # test: worker.run() inline (sygnały direct = synchronicznie), bez QThread
    yield v, con, files
    con.close()


_POL = {"source": "date_obs", "offset_hours": 0, "fallback": True}


def test_rename_lifecycle_stage_commit_restage_undo(rn_view):
    """R1 #1 + R2 #1: stage→commit→re-stage MINTUJE nowy run_id, NIE kasuje 'applied' pierwszego. Fix#1
    (rec#1/wiz#3): re-stage CHOWA leftover „Cofnij" (anty-orphan), a undo skommitowanego runu wraca
    ścieżką CLI (R2 #7). Bezpośrednio po commicie (BEZ re-stage) „Cofnij" celuje w first_run."""
    view, con, files = rn_view
    view._on_rename_stage(_POL)
    assert view._rename_pending_count() == 2
    first_run = view._rename_run_id

    view._on_commit()                                # dispatch → commit renamu (mutex: rename aktywny)
    assert view._rename_run_committed and view._undo_rename_run_id == first_run
    assert view._undo_mode == "rename" and view._undo_btn.isVisibleTo(view)
    assert not any(f.exists() for f in files)        # przemianowane na dysku
    applied = [r for r in writeback.renames_for_run(con, first_run) if r["status"] == "applied"]
    assert len(applied) == 2

    view._on_rename_stage(_POL)                      # committed → MINT nowy run (touched=0, nazwy kanoniczne)
    assert view._rename_run_id != first_run
    still = [r for r in writeback.renames_for_run(con, first_run) if r["status"] == "applied"]
    assert len(still) == 2                           # 'applied' pierwszego NIENARUSZONE (R2 #1, nie clobber)
    assert not view._undo_btn.isVisibleTo(view) and view._undo_mode is None   # fix#1: leftover „Cofnij" zdjęty

    # undo skommitowanego runu wciąż osiągalne ścieżką CLI (R2 #7) → przywraca oryginały
    writeback.undo_renames(con, first_run, now=NOW)
    assert all(f.exists() for f in files)            # oryginalne nazwy wróciły


def test_rename_commit_all_blocked_bez_undo(rn_view):
    """R2 #6: commit z applied=0 (cel już zajęty na dysku) → BEZ „Cofnij", run zwolniony, oryginał nietknięty."""
    view, con, files = rn_view
    view._on_rename_stage(_POL)
    for r in writeback.renames_for_run(con, view._rename_run_id):   # OBCE pliki pod celami → anty-clobber
        with open(r["new_path"], "wb") as f:
            f.write(b"OBCY")
    view._on_commit()
    assert view._rename_run_id is None and view._undo_rename_run_id is None
    assert not (hasattr(view, "_undo_btn") and view._undo_btn.isVisible())
    assert all(f.exists() for f in files)            # oryginały nietknięte


def test_rename_macro_mutex_disabled_tooltip(rn_view):
    """R2 #8: staging makra → „Do stagingu" renamu disabled+tooltip (stan bez klikania); reject makra zwalnia."""
    view, con, files = rn_view
    view.macro_bar.asg_kw.setCurrentText("TELESCOP")
    view.macro_bar.asg_op.setCurrentIndex(0)
    view.macro_bar.asg_expr.setText("EQ6")
    view.macro_bar._emit_stage()
    assert view._pending_count() >= 1
    assert not view.rename_bar.btn_stage.isEnabled()
    assert "makra" in view.rename_bar.btn_stage.toolTip()
    view._on_reject()
    assert view.rename_bar.btn_stage.isEnabled() and view.rename_bar.btn_stage.toolTip() == ""


def test_preview_wspoldzielony_miedzy_klingami(rn_view):
    """R1 #19: podgląd renamu ZDEJMUJE podgląd makra (jeden `_preview`); etykieta kolumny rozróżnia klingę."""
    view, con, files = rn_view
    view.macro_bar.asg_kw.setCurrentText("TELESCOP")
    view.macro_bar.asg_op.setCurrentIndex(0)
    view.macro_bar.asg_expr.setText("EQ6")
    view.macro_bar._emit_preview()
    assert view._preview_owner == "macro" and view.model._preview_label == "makro →"
    view._on_rename_preview(_POL)
    assert view._preview_owner == "rename" and view.model._preview_label == "nazwa →"


def test_undo_mode_init_none_i_dispatch(rn_view):
    """R1 #3: _undo_mode init None; po commicie renamu dispatch woła undo_renames (nie makro-undo)."""
    view, con, files = rn_view
    assert view._undo_mode is None
    view._on_rename_stage(_POL)
    view._on_commit()
    assert view._undo_mode == "rename"
    view._dispatch_undo()
    assert all(f.exists() for f in files)


def test_rename_pending_count_mode_aware_busy(rn_view):
    """R1 #2: pod busy licznik/commit AKTYWNEJ klingi = rename; set_busy(False) re-enable wg rename-pending."""
    view, con, files = rn_view
    view._on_rename_stage(_POL)
    assert view._active_pending_count() == 2 and view.drawer._n == 2   # szuflada mode-aware
    view.set_busy(True)
    assert not view.drawer.btn_commit.isEnabled()
    view.set_busy(False)
    assert view.drawer.btn_commit.isEnabled()                          # wg rename-pending, nie makra


# ---------- fixy adjudykowane z recenzji kodu + audytu GUI ----------

def test_drawer_label_sukcesu_nie_clobber_rename(rn_view):
    """wiz#2/rec#2: po commicie renamu etykieta szuflady = „Przemianowano: N", NIE nadpisana pustostanem
    przez końcowe _refresh_drawer (regresja noty D2)."""
    view, con, files = rn_view
    view._on_rename_stage(_POL)
    view._on_commit()
    assert "Przemianowano" in view.drawer.label.text()
    assert view.drawer.label.text() != "Poczekalnia zmian — pusta"


def test_drawer_label_sukcesu_nie_clobber_makro(wb_view):
    """wiz#2/rec#2: bliźniaczo dla makra — „Zatwierdzono: N" przeżywa końcowe _refresh_drawer."""
    view, con, p = wb_view
    view.macro_bar.asg_kw.setCurrentText("TELESCOP")
    view.macro_bar.asg_op.setCurrentIndex(0)
    view.macro_bar.asg_expr.setText("EQ6")
    view.macro_bar._emit_stage()
    view._on_commit()
    assert "Zatwierdzono" in view.drawer.label.text()


def test_cross_blade_dismiss_undo_bez_zakleszczenia(rn_view):
    """rec#1/wiz#3: commit makra → stage renamu ZDEJMUJE leftover „Cofnij" makra (anty-orphan). Bez tego
    klik stałego „Cofnij" cofał makro osierocając pending renamu = zakleszczenie mutexa do restartu."""
    view, con, files = rn_view
    view.macro_bar.asg_kw.setCurrentText("TELESCOP")
    view.macro_bar.asg_op.setCurrentIndex(0)
    view.macro_bar.asg_expr.setText("EQ6")
    view.macro_bar._emit_stage()
    view._on_commit()
    assert view._undo_btn.isVisibleTo(view) and view._undo_mode == "macro"
    view._on_rename_stage(_POL)                       # nowy staging → leftover „Cofnij" makra ZDJĘTY
    assert not view._undo_btn.isVisibleTo(view) and view._undo_mode is None
    assert view._rename_pending_count() == 2          # staging renamu żyje, nie osierocony


def test_rename_preview_komorka_tylko_nowa_nazwa(rn_view):
    """wiz#1: komórka podglądu renamu pokazuje TYLKO nową nazwę (stara jest w „Ścieżka"); pełne
    stara→nowa w tooltipie (weryfikacja nazwy przed commitem bez scrolla po starym prefiksie)."""
    view, con, files = rn_view
    view._on_rename_preview(_POL)
    from horreum.gui.grid import BASE_COLS
    pcol = len(BASE_COLS) + len(view._columns)
    r = next(i for i, row in enumerate(view.model._rows) if row.get("frame_id"))
    disp = view.model.data(view.model.index(r, pcol), Qt.DisplayRole)
    assert disp and "→" not in disp and disp.startswith("2024")   # tylko nowa nazwa kanoniczna
    tip = view.model.data(view.model.index(r, pcol), Qt.ToolTipRole)
    assert "→" in tip                                              # pełne stara→nowa w tooltipie


def test_rename_commit_powod_w_summary(rn_view):
    """wiz#4: blokada commitu niesie POWÓD w wyniku szuflady, nie tylko liczbę (user pyta „czemu?")."""
    view, con, files = rn_view
    view._on_rename_stage(_POL)
    for r in writeback.renames_for_run(con, view._rename_run_id):   # OBCE pliki pod celami → blocked
        with open(r["new_path"], "wb") as f:
            f.write(b"OBCY")
    view._on_commit()
    assert "zablokowanych" in view.drawer.result.text()
    assert "cel już istnieje" in view.drawer.result.text()         # reprezentatywny reason widoczny


# ---------- F3: pasek zbioru + panele kling (PLAN_ux_redesign §4) ----------

def test_panele_ekskluzywne_i_checkable(view):
    """F3: stack ukryty na starcie; otwarcie → jeden panel; przełączenie → drugi (nigdy oba);
    klik w otwarty → zamknięcie + odznaczony przycisk (F3R#9)."""
    assert not view.panel_stack.isVisibleTo(view)
    view._toggle_panel("macro")
    assert view.panel_stack.isVisibleTo(view) and view.panel_stack.currentWidget() is view.macro_bar
    assert view.sel_bar.btn_macro.isChecked() and not view.sel_bar.btn_rename.isChecked()
    view._toggle_panel("rename")
    assert view.panel_stack.currentWidget() is view.rename_bar
    assert view.sel_bar.btn_rename.isChecked() and not view.sel_bar.btn_macro.isChecked()
    view._toggle_panel("rename")                       # ten sam → zamknij
    assert not view.panel_stack.isVisibleTo(view)
    assert not view.sel_bar.btn_rename.isChecked() and not view.sel_bar.btn_macro.isChecked()


def test_przelaczenie_czysci_cudzy_podglad(rn_view):
    """R#9: podgląd makra aktywny → otwarcie panelu renamu czyści go WPROST handlerem `cleared`
    (właściciel None, kolumna podglądu znika) — właściciel nie może zniknąć z ekranu z żywym podglądem."""
    view, con, files = rn_view
    view._toggle_panel("macro")
    view.macro_bar.asg_kw.setCurrentText("TELESCOP")
    view.macro_bar.asg_op.setCurrentIndex(0)
    view.macro_bar.asg_expr.setText("EQ6")
    view.macro_bar._emit_preview()
    assert view._preview_owner == "macro" and view.model._preview_active()
    view._toggle_panel("rename")                       # cudzy panel → podgląd makra zdjęty
    assert view._preview_owner is None and not view.model._preview_active()


def test_zamkniecie_panelu_zostawia_podglad(rn_view):
    """F3: zamknięcie panelu (≠ przełączenie) ZOSTAWIA podgląd — kolumna podglądu to wartość sama
    w sobie (user chowa panel, żeby obejrzeć grid na pełnej szerokości); własny panel też nie tyka."""
    view, con, files = rn_view
    view._toggle_panel("rename")
    view._on_rename_preview(_POL)
    assert view._preview_owner == "rename" and view.model._preview_active()
    view._toggle_panel("rename")                       # zamknięcie
    assert not view.panel_stack.isVisibleTo(view)
    assert view._preview_owner == "rename" and view.model._preview_active()
    view._toggle_panel("rename")                       # ponowne otwarcie WŁASNEGO → podgląd nietknięty
    assert view.model._preview_active()


def test_staging_przezywa_przelaczenie_paneli(rn_view):
    """F3: pending żyje w poczekalni NIEZALEŻNIE od paneli — przełączenie zdejmuje TYLKO podgląd,
    nie staging; mutex „Do stagingu" drugiej klingi dalej widoczny w jej panelu."""
    view, con, files = rn_view
    view._toggle_panel("macro")
    view.macro_bar.asg_kw.setCurrentText("TELESCOP")
    view.macro_bar.asg_op.setCurrentIndex(0)
    view.macro_bar.asg_expr.setText("EQ6")
    view.macro_bar._emit_stage()
    assert view._pending_count() == 2
    view._toggle_panel("rename")
    assert view._pending_count() == 2                  # staging nietknięty (podgląd ≠ staging)
    assert not view.rename_bar.btn_stage.isEnabled()   # mutex dalej uczciwy
    assert "makra" in view.rename_bar.btn_stage.toolTip()


def test_echo_daty_po_otwarciu_rename_niepuste(rn_view):
    """F3R#4 (kolejność = kontrakt): echo daty policzone OD RAZU przy otwarciu panelu renamu
    (strona → pokaż → echo), nie dopiero po zmianie zaznaczenia."""
    view, con, files = rn_view
    assert view.rename_bar.lbl_primary.text() == "—"   # zastany placeholder z __init__
    view._toggle_panel("rename")
    assert view.rename_bar.lbl_primary.text().startswith("Wsad:")   # echo wsadu żywe na otwarciu


def test_pusty_zbior_gasi_wydaj_nie_panele(view):
    """F3R#2: pusty zbiór → „Wydaj na stół…" disabled+tooltip; przyciski-panele ŻYWE (gating
    checkable = pułapka disabled-but-checked-open); „★ Zapisz widok" żywy."""
    view.filter_panel.filterApplied.emit({"keyword": "OBJECT", "operator": "eq", "value": "BRAK"})
    assert view.count_label.text() == "0 klatek"
    assert not view.sel_bar.btn_proj.isEnabled()
    assert "brak klatek" in view.sel_bar.btn_proj.toolTip()
    assert view.sel_bar.btn_macro.isEnabled() and view.sel_bar.btn_rename.isEnabled()
    assert view.sel_bar.btn_save.isEnabled()


def test_set_busy_gasi_wydaj(view):
    """F3R#7: podczas etapu pipeline'u „Wydaj na stół…" gaśnie; po etapie wraca wg widocznych."""
    assert view.sel_bar.btn_proj.isEnabled()
    view.set_busy(True)
    assert not view.sel_bar.btn_proj.isEnabled()
    view.set_busy(False)
    assert view.sel_bar.btn_proj.isEnabled()


def test_kryteria_slowami_na_pasku(view):
    """F3: pasek odbija kryteria zbioru słowami (tooltip = pełny tekst); flagi perspektyw spoza
    silnika (Duplikaty) doklejane „ · "."""
    assert view.sel_bar.criteria_label.toolTip() == "wszystkie klatki"
    view.filter_panel.filterApplied.emit({"keyword": "OBJECT", "operator": "eq", "value": "M51"})
    assert view.sel_bar.criteria_label.toolTip() == "OBJECT = M51"
    idx = view.combo_persp.findText("Duplikaty")
    view.combo_persp.setCurrentIndex(idx)
    assert "tylko duplikaty" in view.sel_bar.criteria_label.toolTip()
