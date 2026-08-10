"""Widok „Klatki" (PLAN_gui_grid) — testy STERUJĄCE realnym oknem Qt (offscreen). Model 3 stanów +
sort + grupowanie; FilterPanel → drzewo; FramesView refresh/filtr/perspektywa. `importorskip` na poziomie
modułu (§9.4): bez PySide6 plik się POMIJA (pełny pytest bez Qt zostaje prawdziwy)."""
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from horreum import db, naming, pivot as pivot_mod, writeback
from horreum.gui import queries, rows as rows_mod

from PySide6.QtCore import QPoint, Qt
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

def test_model_klatka_zastapiona_mowi_o_tym_WPROST(gcon):
    """Decyzja Zdzinia 0809 („z widocznym nagrobkiem"): klatka zastąpiona ZOSTAJE w gridzie i ma się
    tłumaczyć sama. Trzy nośniki, bo każdy zawodzi osobno: tło (motyw, daltonizm), tooltip (wymaga
    najechania) i TEKST KOMÓRKI — ten ostatni jest jedynym, który widać zawsze.

    PRECEDENCJA JEST TU TREŚCIĄ, NIE KOLEJNOŚCIĄ `if`-ów: zastąpiona nie ma ani jednej obecnej kopii,
    więc dawny warunek uznawał ją za ZNIKNIĘTĄ — czyli za robotę („znajdź plik"), której nie ma.
    Wiersz zniknięty obok pilnuje, że zawężenie nie zjadło tamtego stanu."""
    from horreum.gui.grid import GridTableModel, BASE_COLS
    from horreum.gui import grid as grid_mod
    wspolne = {"kind": "light", "camera_model": None, "telescope_label": None,
               "telescop_canon": None, "object_canon": None, "object_raw": None,
               "filter_canon": None, "_telescope": None, "_object": None}
    base = [
        {"frame_id": 1, "path": "/a/zywa.fits", "present": 1, "n_present": 1,
         "superseded_by": None, **wspolne},
        {"frame_id": 4, "path": "/a/znikla.fits", "present": 0, "n_present": 0,
         "superseded_by": None, **wspolne},
        {"frame_id": 5, "path": None, "present": None, "n_present": 0,
         "superseded_by": 99, **wspolne},
    ]
    m = GridTableModel()
    m.set_data(base, pivot_mod.build_pivot([1, 4, 5], [], []), [])
    kol_path = [k for _, k in BASE_COLS].index("path")

    # Wiersze adresujemy PO TREŚCI, nie po indeksie: model sortuje, więc pozycja jest jego decyzją,
    # a test ma pytać o zachowanie komórki, nie o kolejność (inaczej pada przy zmianie sortu).
    teksty = [m.data(m.index(i, kol_path), Qt.DisplayRole) for i in range(m.rowCount())]
    i_zast = teksty.index("zastąpiona przez #99")
    i_znik, i_zywa = teksty.index("znikla.fits"), teksty.index("zywa.fits")

    assert "#99" in m.data(m.index(i_zast, kol_path), Qt.ToolTipRole)
    assert m.data(m.index(i_zast, 0), Qt.BackgroundRole) == grid_mod._COLORS["superseded_bg"]
    # …i NIE jest malowana jak zniknięta, choć obecnej kopii nie ma tak samo
    assert m.data(m.index(i_zast, 0), Qt.BackgroundRole) != grid_mod._COLORS["vanished_bg"]
    # regresja: wiersz naprawdę zniknięty zostaje zniknięty
    assert m.data(m.index(i_znik, 0), Qt.BackgroundRole) == grid_mod._COLORS["vanished_bg"]
    assert m.data(m.index(i_zywa, 0), Qt.BackgroundRole) is None


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
    assert view.count_label.text() == "4 klatki"
    assert view.model.rowCount() >= 4  # 4 klatki (+ ewentualne nagłówki grup, tu brak)


def test_view_filtr_gain(view):
    view.filter_panel.add_row()
    view.filter_panel._rows[0]["kw"].setCurrentText("GAIN")
    view.filter_panel._rows[0]["op"].setCurrentIndex(0)  # eq
    view.filter_panel._rows[0]["val"].setText("100")
    view.filter_panel._apply()
    assert view.count_label.text() == "2 klatki"  # f1,f2


def test_view_filtr_odwrocony(view):
    """GAIN=100 odwrócony → uniwersum − {f1,f2} = {f3,f4} (XISF bez cards wchodzi przez uniwersum)."""
    view.filter_panel.add_row()
    view.filter_panel._rows[0]["kw"].setCurrentText("GAIN")
    view.filter_panel._rows[0]["op"].setCurrentIndex(0)  # eq
    view.filter_panel._rows[0]["val"].setText("100")
    view.filter_panel.chk_invert.setChecked(True)
    view.filter_panel._apply()
    assert view.count_label.text() == "2 klatki"


def test_view_perspektywa_z_not_przezywa_zastosuj(view):
    """Round-trip R#1: filtr perspektywy z korzeniem NOT → panel go odbija → „Zastosuj" NIE kasuje
    negacji (scenariusz P3-3 piętro wyżej: bez poprawki set_tree pierwszy Zastosuj gubił NOT)."""
    tree = {"op": "NOT", "conditions": [{"op": "AND", "conditions": [
        {"keyword": "GAIN", "operator": "eq", "value": "100"},
    ]}]}
    view._filter_tree = tree
    view.filter_panel.set_tree(tree)      # ścieżka _on_perspective (P3-3)
    view.refresh()
    assert view.count_label.text() == "2 klatki"
    view.filter_panel._apply()            # user klika „Zastosuj" bez zmian
    assert view._filter_tree == tree      # negacja przeżywa
    assert view.count_label.text() == "2 klatki"


def test_view_perspektywa_duplikaty(view):
    idx = view.combo_persp.findText("Duplikaty")
    view.combo_persp.setCurrentIndex(idx)
    assert view.count_label.text() == "1 klatka"  # tylko f1 (n_present=2)


def test_apply_object_facet_sumuje_dwie_nazwy_celu(view, gcon):
    """T5e (most planer→grid, D-0731-7): jeden cel katalogu bywa w archiwum pod DWIEMA nazwami
    (`IC410` ORAZ `LBN807`, D-T2-d), więc seam bierze LISTĘ par i pokazuje ich SUMĘ. Reużywa
    istniejący facet Obiekt — zero drugiej ścieżki filtrowania (SPOT `facet_model.compose`)."""
    gcon.executemany("INSERT INTO object (id, canon, kind) VALUES (?,?,?)",
                     [(1, "IC410", "deep_sky"), (2, "LBN807", "deep_sky")])
    gcon.execute("UPDATE frame SET object_id = 1 WHERE id = 1")
    gcon.execute("UPDATE frame SET object_id = 2 WHERE id = 2")
    gcon.commit()
    view.refresh()
    view.apply_object_facet([(1, "IC410")])
    assert view.count_label.text() == "1 klatka"
    view.apply_object_facet([(1, "IC410"), (2, "LBN807")])
    assert view.count_label.text() == "2 klatki"          # SUMA obu nazw, nie jedna z nich
    assert view._facet_state["object"]["in"] == [[1, "IC410"], [2, "LBN807"]]


def test_apply_object_facet_odslania_zaznaczenie_w_listwie(view, gcon):
    """Dług P-A #1 (firsthand 2026-08-01): listwa odtwarza pozycję scrolla przy każdym przeładowaniu
    — słusznie dla kliku W listwie, szkodliwie dla wejścia Z ZEWNĄTRZ. Zmierzone przed poprawką:
    `✓ NGC7000` stało na pozycji 36/48 przy scrollu 0, więc most „Pokaż klatki celu" wyglądał
    jak brak reakcji. Odsłonięcie jest JEDNORAZOWE — kolejny refresh nie ma prawa skakać."""
    gcon.executemany("INSERT INTO object (id, canon, kind) VALUES (?,?,?)",
                     [(1, "IC410", "deep_sky"), (2, "LBN807", "deep_sky")])
    gcon.execute("UPDATE frame SET object_id = 1 WHERE id = 1")
    gcon.execute("UPDATE frame SET object_id = 2 WHERE id = 2")
    gcon.commit()
    view.refresh()

    revealed = []
    rail = view.facet_rail
    orig = rail._reveal
    rail._reveal = lambda r: (revealed.append(r), orig(r))[1]
    view.apply_object_facet([(2, "LBN807")])
    assert revealed == [("object", 2)]                    # pierwsza para — most oddaje sumę nazw
    assert view._reveal_facet is None                     # zużyte przy pierwszym przeładowaniu
    view.refresh()
    assert revealed == [("object", 2), None]              # kolejny refresh NIE przewija listy


def test_apply_object_facet_zdejmuje_perspektywe_i_filtr(view, gcon):
    """Wejście z zewnątrz definiuje CAŁY zbiór: perspektywa „Duplikaty" i filtr advanced nie mają
    prawa dołożyć się do klatek celu (inaczej ekran pokazałby przecięcie i skłamał, czyje to klatki)."""
    gcon.execute("INSERT INTO object (id, canon, kind) VALUES (1, 'IC410', 'deep_sky')")
    gcon.execute("UPDATE frame SET object_id = 1 WHERE id IN (1, 2)")
    gcon.commit()
    view.combo_persp.setCurrentIndex(view.combo_persp.findText("Duplikaty"))
    view._filter_tree = {"keyword": "GAIN", "operator": "eq", "value": "100"}
    view.apply_object_facet([(1, "IC410")])
    assert view._only_dups is False and view._filter_tree is None
    assert view.count_label.text() == "2 klatki"


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
    assert view.count_label.text() == "3 klatki"                    # f1,f2,f4
    view.facet_rail._on_item_clicked(_rail_item(view, "kind", "light"))
    assert view._facet_state == {"kind": {"ex": [["light", "light"]]}}
    assert view.count_label.text() == "1 klatka"                    # uniwersum − lighty = f3
    view.facet_rail._on_item_clicked(_rail_item(view, "kind", "light"))
    assert view._facet_state == {}
    assert view.count_label.text() == "4 klatki"


def test_facet_prawy_klik_wyklucza_jednym_gestem(view):
    """P-C: prawy klik na wartości = ⊖ WPROST i z powrotem — bez stanu pośredniego `in`, na którym
    zbiór zwężał się do jednej wartości. Ten sam widok, ta sama normalizacja co lewy klik."""
    lw = view.facet_rail._lists["kind"]
    it = _rail_item(view, "kind", "light")
    view.facet_rail._on_item_right_clicked(lw, lw.visualItemRect(it).center())
    assert view._facet_state == {"kind": {"ex": [["light", "light"]]}}
    assert view.count_label.text() == "1 klatka"                    # uniwersum − lighty = f3
    it = _rail_item(view, "kind", "light")                          # listwa przebudowana
    view.facet_rail._on_item_right_clicked(lw, lw.visualItemRect(it).center())
    assert view._facet_state == {}
    assert view.count_label.text() == "4 klatki"


def test_facet_prawy_klik_w_pustke_bez_skutku(view):
    """Gest celuje we WARTOŚĆ, nie w listę — klik pod ostatnim wierszem nie ma prawa nic zmienić."""
    view.facet_rail._on_item_clicked(_rail_item(view, "kind", "light"))
    before = dict(view._facet_state)
    lw = view.facet_rail._lists["kind"]
    view.facet_rail._on_item_right_clicked(lw, QPoint(5, lw.sizeHintForRow(0) * (lw.count() + 4)))
    assert view._facet_state == before


def test_facet_sibling_lista_pokazuje_sasiadow(view):
    """F4R#1: po zawężeniu do light lista Rodzaju NADAL pokazuje master_flat (sibling-set — inaczej
    OR-wewnątrz byłby nieosiągalny); aktywna wartość znaczona ✓."""
    view.facet_rail._on_item_clicked(_rail_item(view, "kind", "light"))
    lw = view.facet_rail._lists["kind"]
    values = {lw.item(i).data(Qt.UserRole)[1] for i in range(lw.count())}
    assert values == {"light", "master_flat"}
    assert _rail_item(view, "kind", "light").text().startswith("✓ ")
    it = _rail_item(view, "kind", "master_flat")
    assert (it.text(), it.data(rows_mod.SECONDARY)) == ("master_flat", "(1)")


def test_facet_ex_render_ukryte(view):
    """F4R2#1: „(n)" przy ⊖ znaczy „ile wróci po zdjęciu" — render to nazywa, nie udaje wkładu."""
    view.facet_rail._on_item_clicked(_rail_item(view, "kind", "light"))
    view.facet_rail._on_item_clicked(_rail_item(view, "kind", "light"))   # in → ex
    it = _rail_item(view, "kind", "light")
    assert (it.text(), it.data(rows_mod.SECONDARY)) == ("⊖ light", "(+3 ukryte)")


def test_facet_pin_aktywnego_poza_siblingiem(view):
    """Aktywny wybór ZAWSZE renderowany: ⊖ master_flat + advanced GAIN-istnieje odcina master_flat
    z sibling-setu (XISF bez cards) → wiersz zostaje PINowany (niewidzialny filtr = UI kłamie)."""
    view.facet_rail._on_item_clicked(_rail_item(view, "kind", "master_flat"))
    view.facet_rail._on_item_clicked(_rail_item(view, "kind", "master_flat"))  # in → ex
    view.filter_panel.add_row()
    view.filter_panel._rows[0]["kw"].setCurrentText("GAIN")
    view.filter_panel._rows[0]["op"].setCurrentIndex(8)   # 'istnieje'
    view.filter_panel._apply()
    assert view.count_label.text() == "2 klatki"          # f1,f2 (GAIN) − master_flat i tak poza
    it = _rail_item(view, "kind", "master_flat")
    assert (it.text(), it.data(rows_mod.SECONDARY)) == ("⊖ master_flat", "(+0 ukryte)")


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


def test_facet_object_godziny_sufiks_i_guard_ex(qapp):
    """F7 §8: wiersz obiektu „in"/none niesie sufiks godzin (extras) + tooltip per filtr. Guard
    DD-render (recenzja #1): obiekt ⊖ JEST w extras (sibling-set obiektu ZAWIERA wykluczone), a MIMO
    TO wiersz nie dokleja godzin. Obiekt bez wpisu extras → bez sufiksu.

    P1 (wiz F7 #F1/#F2/#F4): licznik i godziny mieszkają w prawych kolumnach delegata, NAZWA zostaje
    sama w `text()`. Doklejanie do tekstu przepychało listwę przez 220 px w poziomy scrollbar
    i tłukło skanowalność kolumny godzin. **Człony są ROZDZIELONE (wiz P1 #4):** licznik w
    `rows.SECONDARY`, godziny w `rows.TERTIARY` — sklejone w jeden run przesuwały licznik o szerokość
    ogona godzin (zmierzone na żywej pf4: „(301) · 60.4 h" kończyło „(n)" 108 px od prawej,
    „(60) · 3.0 h" 96 px), więc kolumny liczb nie dało się skanować."""
    from horreum.gui import rows
    from horreum.gui.facets import FacetRail
    rail = FacetRail()
    counts = {"object": [(1, "M51", 5), (2, "NGC7000", 3), (7, "IC434", 2)],
              "filter": [], "kind": [], "telescope": [], "night": []}
    extras = {"object": {1: (" · 1.0 h", "Ha: 1.0 h"),
                         2: (" · 2.0 h", "OIII: 2.0 h")}}     # NGC7000 (⊖) JEST w extras
    state = {"object": {"in": [[1, "M51"]], "ex": [[2, "NGC7000"]]}}
    rail.set_data(counts, state, extras)

    def _item(v):
        lw = rail._lists["object"]
        for i in range(lw.count()):
            if lw.item(i).data(Qt.UserRole)[1] == v:
                return lw.item(i)
        raise AssertionError(f"brak {v}")

    assert _item(1).text() == "✓ M51"                        # człon 1 = SAMA nazwa (+ marker stanu)
    assert _item(1).data(rows.SECONDARY) == "(5)"            # in → SAM licznik (człon drugi)
    assert _item(1).data(rows.TERTIARY) == " · 1.0 h"        # godziny = własna kolumna (człon trzeci)
    assert _item(1).toolTip() == "Ha: 1.0 h"
    assert _item(2).text() == "⊖ NGC7000"
    assert _item(2).data(rows.SECONDARY) == "(+3 ukryte)"    # ex → BEZ godzin mimo wpisu w extras
    assert _item(2).data(rows.TERTIARY) is None
    assert _item(2).toolTip() == ""
    assert _item(7).text() == "IC434"
    assert _item(7).data(rows.SECONDARY) == "(2)"            # brak wpisu extras → sam licznik
    assert _item(7).data(rows.TERTIARY) is None
    assert _item(7).toolTip() == ""
    # Kolumna godzin ma WSPÓLNĄ szerokość dla listy (`fit_tertiary` po wypełnieniu) — dopiero to
    # ustawia liczby w kolumnę. Grupa bez adnotacji zostaje przy układzie dwuczłonowym (0).
    assert rail._lists["object"].itemDelegate()._tertiary_w > 0
    assert rail._lists["kind"].itemDelegate()._tertiary_w == 0


def test_facet_wyczysc_zbior(view):
    """Wiz F4 #3: „× Wyczyść zbiór" zdejmuje facety + advanced JEDNYM klikiem; uczciwy disabled,
    gdy nie ma co zdjąć (preset „Przegląd" jest no-opem, gdy już wybrany — to była jedyna droga)."""
    assert not view.sel_bar.btn_clear.isEnabled()          # nic do czyszczenia
    view.facet_rail._on_item_clicked(_rail_item(view, "kind", "light"))
    view.filter_panel._rows[0]["kw"].setCurrentText("GAIN")
    view.filter_panel._rows[0]["op"].setCurrentIndex(8)    # 'istnieje'
    view.filter_panel._apply()
    assert view.count_label.text() == "2 klatki"           # lighty ∩ GAIN
    assert view.sel_bar.btn_clear.isEnabled()
    view.sel_bar.btn_clear.click()
    assert view._facet_state == {} and view._filter_tree is None
    assert view.count_label.text() == "4 klatki"
    assert not view.sel_bar.btn_clear.isEnabled()


def test_facet_preset_zeruje_stan(view):
    """F4R#2: perspektywa definiuje CAŁY zbiór — wczytanie presetu bez `facets` zdejmuje facety."""
    view.facet_rail._on_item_clicked(_rail_item(view, "kind", "light"))
    assert view._facet_state
    idx = view.combo_persp.findText("Przegląd")
    view.combo_persp.setCurrentIndex(idx) if idx != view.combo_persp.currentIndex() else view._on_perspective()
    assert view._facet_state == {}
    assert view.count_label.text() == "4 klatki"


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
    assert v.count_label.text() == "2 klatki"             # lighty ∩ GAIN = f1,f2
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Zlozona", True)))
    v._save_perspective()
    assert v.combo_persp.currentData() == ("saved", "Zlozona")   # F4R2#6: etykieta nie kłamie
    # odejdź na preset (F4R#2: preset zeruje facety)…
    v.combo_persp.setCurrentIndex(v.combo_persp.findText("Przegląd"))
    assert v._facet_state == {}
    assert v.count_label.text() == "4 klatki"
    # …i wróć do zapisanej: facety wracają do raila, advanced do panelu
    for i in range(v.combo_persp.count()):
        if v.combo_persp.itemData(i) == ("saved", "Zlozona"):
            v.combo_persp.setCurrentIndex(i)
            break
    assert v._facet_state == {"kind": {"in": [["light", "light"]]}}
    assert v.count_label.text() == "2 klatki"
    assert _rail_item(v, "kind", "light").text().startswith("✓ ")
    v.filter_panel._apply()                               # „Zastosuj" panelu — facety przeżywają
    assert v._facet_state == {"kind": {"in": [["light", "light"]]}}
    assert v.count_label.text() == "2 klatki"


def test_perspektywa_ladujaca_z_bazy_przezywa_nowe_okno(view_settings, monkeypatch, gcon):
    """I-1 (D-P-I-3): nazwany widok jest własnością ARCHIWUM. Zapis w jednym oknie, odczyt
    w DRUGIM zbudowanym nad tą samą bazą — to jest w miniaturze „zapisz na stacji, otwórz na
    laptopie", którego rejestr użytkownika nie umiał."""
    from PySide6.QtWidgets import QInputDialog

    from horreum.gui.grid import FramesView
    v = view_settings
    v.facet_rail._on_item_clicked(_rail_item(v, "kind", "light"))
    v.refresh()
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Z bazy", True)))
    v._save_perspective()
    assert queries.perspectives(gcon)[0][0] == "Z bazy"

    drugie = FramesView(gcon, now_fn=None)                 # inne okno, ta sama baza
    idx = next(i for i in range(drugie.combo_persp.count())
               if drugie.combo_persp.itemData(i) == ("saved", "Z bazy"))
    drugie.combo_persp.setCurrentIndex(idx)
    assert drugie._facet_state == {"kind": {"in": [["light", "light"]]}}


def test_perspektywy_z_rejestru_wciagaja_sie_raz_i_nie_puchna(qapp, gcon, monkeypatch):
    """Wydanie publiczne trzymało perspektywy w `QSettings` (D-B), więc przeniesienie kanonu do
    bazy BEZ importu skasowałoby użytkownikom nazwane widoki — regresja, nie sprzątanie (FORWARD).
    Import jest idempotentny, bo woła się przy KAŻDYM otwarciu widoku: drugie okno nie ma prawa
    dopisać ani wiersza, ani eventu."""
    from PySide6.QtCore import QSettings

    from horreum.gui.grid import FramesView
    store = {"grid/perspectives": json.dumps(
        {"Stara": {"filter": None, "columns": ["OBJECT"], "only_dups": True}})}
    monkeypatch.setattr(QSettings, "value", lambda self, k, d=None: store.get(k, d))
    monkeypatch.setattr(QSettings, "setValue", lambda self, k, v: store.__setitem__(k, v))

    FramesView(gcon, now_fn=None)
    assert dict(queries.perspectives(gcon))["Stara"]["only_dups"] is True
    ev = gcon.execute("SELECT count(*) FROM event").fetchone()[0]

    FramesView(gcon, now_fn=None)                          # drugie otwarcie: zero ruchu
    assert len(queries.perspectives(gcon)) == 1
    assert gcon.execute("SELECT count(*) FROM event").fetchone()[0] == ev
    # Rejestru NIE czyścimy — kopia ratuje kogoś, kto wróci na starsze wydanie
    assert "grid/perspectives" in store


def test_perspektywa_w_starym_formacie_nie_udaje_pustego_filtra(view_settings):
    """Wiersz z migracji 0013 (`legacy_sql`) ZOSTAJE na liście z ostrzeżeniem, ale wybór go nie
    stosuje: pusty spec zdjąłby filtr i wyglądał na „perspektywa pokazuje wszystko"."""
    v = view_settings
    v.con.execute("INSERT INTO saved_query(name, spec_json, created_at) VALUES ('Stary', ?, 't')",
                  (json.dumps({"legacy_sql": "SELECT 1"}),))
    v.con.commit()
    v._load_facets()
    idx = next(i for i in range(v.combo_persp.count())
               if v.combo_persp.itemData(i) == ("saved", "Stary"))
    assert v.combo_persp.itemText(idx).endswith("⚠")       # widoczna, nie ukryta
    v._only_dups = True                                     # stan, który pusty spec by wyzerował
    v.combo_persp.setCurrentIndex(idx)
    assert v._only_dups is True                             # nietknięty — perspektywa NIE zadziałała


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
    from horreum.gui import grid as grid_mod        # F6: kolory stanów w przeładowywalnym _COLORS
    assert bg == grid_mod._COLORS["touched_bg"]
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
    from horreum.gui.wb_worker import WritebackWorker   # P-D: wykonawca wspólny dla dwóch powierzchni
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
    from horreum.gui.wb_worker import WritebackWorker   # P-D: wykonawca wspólny dla dwóch powierzchni
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


# ---------- RenameBar: edytor wzoru (v2 §5 — folder/orig/per-token, D-I4) ----------

def test_renamebar_edytor_domyslny_z_disc(qapp):
    """Domyślny preset edytora = DEFAULT_TEMPLATE (Z `disc` — D-I4 bezpieczny domyśl); policy niesie wzór."""
    from horreum.gui.grid import RenameBar
    bar = RenameBar()
    assert bar.policy()["template"] == list(naming.DEFAULT_TEMPLATE)
    assert "disc" in bar.policy()["template"]


def test_renamebar_edytor_folder_orig_serializuja(qapp):
    """Rzędy folder/orig serializują się do dict-specyfikacji; kolejność zachowana."""
    from horreum.gui.grid import RenameBar
    bar = RenameBar()
    bar.template_editor.set_template(["datetime", {"t": "folder", "n": 2}, {"t": "orig", "re": r"gain\d+"}])
    tmpl = bar.policy()["template"]
    assert tmpl == ["datetime", {"t": "folder", "n": 2}, {"t": "orig", "re": r"gain\d+"}]


def test_renamebar_edytor_usun_disc_i_przywroc(qapp):
    """User usuwa rząd `disc` (czyste nazwy) → wzór bez disc; „Przywróć domyślny" wraca do DEFAULT."""
    from horreum.gui.grid import RenameBar
    bar = RenameBar()
    disc_row = next(r for r in bar.template_editor._rows() if r.spec() == "disc")
    bar.template_editor._remove(disc_row)
    assert "disc" not in bar.policy()["template"]
    bar.template_editor._restore_default()
    assert bar.policy()["template"] == list(naming.DEFAULT_TEMPLATE)


def test_renamebar_edytor_pusty_pokazuje_hint(qapp):
    """Wiz #3: usunięcie WSZYSTKICH rzędów → hint widoczny, wzór pusty (bezpieczny: kolizja→skip)."""
    from horreum.gui.grid import RenameBar
    bar = RenameBar()
    for row in list(bar.template_editor._rows()):
        bar.template_editor._remove(row)
    assert bar.policy()["template"] == []
    assert not bar.template_editor._empty_hint.isHidden()     # off-screen: flaga hide, nie isVisible
    bar.template_editor._add_row("kind")
    assert bar.template_editor._empty_hint.isHidden()


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


# ---------- P-C: „Zniknięte" mówi KIEDY (wiz P5 #11) ----------

def _path_tip(view, frame_id):
    r = next(i for i, row in enumerate(view.model._rows) if row.get("frame_id") == frame_id)
    return view.model.data(view.model.index(r, 0), Qt.ToolTipRole)     # kolumna 0 = „Ścieżka"


def test_tooltip_znikietej_niesie_date_znikniecia(view, gcon):
    """Wizytacja P5 #11: przy szukaniu backupu liczy się katalog I data. Katalog tooltip niósł od
    początku (pełna ścieżka); datę bierze `location.last_verified_at`, którą stempluje jedyna droga
    zapisu `present=0` (`repo.mark_location_vanished`) — do minut, bez „T"."""
    gcon.execute("UPDATE location SET last_verified_at = ? WHERE frame_id = 4",
                 ("2026-07-22T18:21:44.4+00:00",))
    gcon.commit()
    view.refresh()
    tip = _path_tip(view, 4)
    assert "/a/f4.fits" in tip                                # katalog: pełna ścieżka jak dotąd
    assert "2026-07-22 18:21" in tip and "zniknięta" in tip


def test_tooltip_znikietej_bez_daty_nie_zmysla(view, gcon):
    """Baza sprzed markera (`last_verified_at IS NULL`) → człon BEZ daty. Brak faktu nie ma prawa
    udawać faktu, a „—" w zdaniu o zniknięciu czytałoby się jak data."""
    gcon.execute("UPDATE location SET last_verified_at = NULL WHERE frame_id = 4")
    gcon.commit()
    view.refresh()
    tip = _path_tip(view, 4)
    assert "zniknięta" in tip and "2026" not in tip.split("f4.fits")[-1]


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


def test_kropka_poczekalni_przelacza_role_i_przepolerowuje(view, monkeypatch):
    """Wizytacja P-C #9: mechanika `_set_role` była bez bramki, a bez `unpolish`/`polish` sam
    `setProperty` NIE przemalowuje żywego widżetu — usunięcie tych dwóch linii przeszłoby całą
    baterię, a kropka poczekalni zamarłaby na kolorze z chwili budowy."""
    from horreum.gui import grid as grid_mod
    polished = []
    real = grid_mod._set_role
    monkeypatch.setattr(grid_mod, "_set_role",
                        lambda w, role: (polished.append(role), real(w, role))[1])
    view.drawer.set_count(7)
    assert view.drawer.dot.property("role") == "warn" and view.drawer.dot.text() == "●"
    view.drawer.set_count(0)
    assert view.drawer.dot.property("role") == "secondary" and view.drawer.dot.text() == "○"
    assert polished == ["warn", "secondary"]


def test_set_role_niesie_repolish():
    """Kontrakt helpera pilnowany STATYCZNIE: `_set_role` musi wołać `unpolish` i `polish`.
    Spy na `lbl.style()` byłby gorszy niż brak testu — `style()` oddaje WSPÓŁDZIELONY styl
    aplikacji, więc podmiana metody wyciekłaby na wszystkie kolejne testy sesji."""
    import ast
    import inspect
    from horreum.gui import grid as grid_mod
    body = ast.parse(inspect.getsource(grid_mod._set_role))
    called = {n.func.attr for n in ast.walk(body)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert {"unpolish", "polish"} <= called


def test_afordancja_prawego_klika_na_listwie(view):
    """Wizytacja P-C #2: gest bez menu jest niewidoczny. Tooltip listy nazywa OBA kliki — inaczej
    skrót 2→1 istnieje wyłącznie dla tego, kto czytał commit."""
    for lw in view.facet_rail._lists.values():
        assert "Prawy klik" in lw.toolTip()


def test_zlota_akcja_zbioru_ma_wage(view):
    """Wiz F3 #3 (dług zamknięty w P-C): JEDNA złota akcja na miejsce niesie wagę wizualną —
    „Wydaj na stół…" bold, reszta paska nie. Waga, nie kolor: złoto motywu ma w jasnej skórce
    2,7:1 i jako tekst nie dochodzi do progu AA (ta sama pułapka co wiz T5 N5)."""
    assert view.sel_bar.btn_proj.font().bold()
    for other in (view.sel_bar.btn_clear, view.sel_bar.btn_macro,
                  view.sel_bar.btn_rename, view.sel_bar.btn_save):
        assert not other.font().bold()


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


def test_pustostan_rozroznia_filtr_od_pustej_bazy(qapp, tmp_path, monkeypatch):
    """Wiz F5 #8: pusty grid mówi DWIE różne rzeczy. Na bazie z klatkami „zmień filtr lub
    perspektywę" jest prawdą; na PUSTEJ bazie wysyłałoby usera w ślepy zaułek (nie ma czego
    filtrować) — tam komunikat kieruje po dostawę."""
    from PySide6.QtCore import QSettings
    monkeypatch.setattr(QSettings, "value", lambda self, k, d=None: d)
    monkeypatch.setattr(QSettings, "setValue", lambda self, k, v: None)
    from horreum.gui.grid import _EMPTY_DB, _EMPTY_FILTER, FramesView
    from horreum.gui import i18n                          # _EMPTY_* to KLUCZE (rollout i18n) — rozwiąż t()

    con = db.open_db(str(tmp_path / "pusta.db"))          # świeża baza: zero klatek
    try:
        v = FramesView(con, now_fn=None)
        assert v.empty.isVisible() or v._n_total == 0
        assert v.empty.text() == i18n.t(_EMPTY_DB)
    finally:
        con.close()

    con2 = db.open_db(str(tmp_path / "pelna.db"))
    _seed(con2)
    try:
        v2 = FramesView(con2, now_fn=None)
        assert v2.empty.text() == i18n.t(_EMPTY_FILTER)   # niepusta baza → wariant filtrowy
        v2.filter_panel.filterApplied.emit({"keyword": "OBJECT", "operator": "eq", "value": "BRAK"})
        assert v2._n_total == 0 and v2.empty.text() == i18n.t(_EMPTY_FILTER)
    finally:
        con2.close()


def test_en_render_grid_z_katalogu(qapp, tmp_path):
    """§5 (rollout grid): `set_lang('en')` PRZED budową → nagłówki bazowe, akcje paska zbioru, presety
    i pusty stan renderują EN z katalogu (stałe BASE_COLS/PRESETS trzymają KLUCZE). Split tożsamość/
    tekst presetu: WYŚWIETLANIE = EN, `itemData` = tożsamość PL → `apply_perspective` po tożsamości
    działa pod EN. Autouse-fixture wraca na PL."""
    from horreum.gui import i18n
    from horreum.gui.grid import FramesView, _EMPTY_DB
    i18n.set_lang("en")
    con = db.open_db(str(tmp_path / "en.db"))
    try:
        v = FramesView(con, now_fn=None)
        assert v.model.headerData(0, Qt.Horizontal, Qt.DisplayRole) == "Path"   # BASE_COLS[0]=col.path
        assert v.sel_bar.btn_proj.text() == "Serve to table…"
        assert v.sel_bar.btn_save.text() == "★ Save view"
        assert v.empty.text() == i18n.t(_EMPTY_DB)                              # pusta baza → wariant EN
        # preset: WYŚWIETLANIE EN, tożsamość PL w itemData (split)
        assert v.combo_persp.itemText(0) == "Review"
        assert v.combo_persp.itemData(0) == ("preset", "Przegląd")
        v.apply_perspective("Duplikaty")   # po TOŻSAMOŚCI PL — działa mimo EN wyświetlania
        assert v.combo_persp.currentData() == ("preset", "Duplikaty")
        # facety (rollout drobne): _GROUPS tytuły + szukajka trzymają KLUCZE → EN z katalogu
        from PySide6.QtWidgets import QLabel
        assert v.facet_rail.search.placeholderText() == "search object (Ctrl+F)…"
        titles = {lb.text() for lb in v.facet_rail.findChildren(QLabel)}
        assert {"Object", "Filter", "Kind", "Telescope", "Night"} <= titles
    finally:
        con.close()


def test_panel_pol_pokrycie_w_prawej_kolumnie(view):
    """Wiz F3 #4: pokrycie doklejone do keyworda było ucięte przy 1200 px (splitter 1:4 skąpi lewej
    stronie). Licznik idzie w człon drugi (prawa kolumna), a panel dostaje to samo minimum
    szerokości co listwa facetów."""
    from horreum.gui.facets import RAIL_MIN_W
    lst = view.fields.list
    it = next(lst.item(i) for i in range(lst.count()) if lst.item(i).data(Qt.UserRole) == "OBJECT")
    assert it.text() == "OBJECT"                          # nazwa SAMA — bez doklejonego licznika
    assert it.data(rows_mod.SECONDARY) == "(3)"           # f1,f2,f4 mają OBJECT
    assert view.fields.minimumWidth() == RAIL_MIN_W


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


def test_flaga_panelu_daty_nazywa_wage(rn_view):
    """Wizytacja P-C #7: „Δ niepełnogodzinna!" (ostrzeżenie) i „brak źródła czasu" (stan
    informacyjny) nosiły tę samą czerwień co „Etap padł" Dostawy. Akcent, który krzyczy
    o wszystkim, nie mówi o niczym — czerwień zostaje dla awarii."""
    view, con, files = rn_view
    view._toggle_panel("rename")
    bar = view.rename_bar
    bar.set_echo("", "", "", "Δ niepełnogodzinna!")
    assert bar.lbl_flag.property("role") == "warn"
    bar.set_echo("", "", "", "brak źródła czasu", flag_role="secondary")
    assert bar.lbl_flag.property("role") == "secondary"


# --- panel RODOWODU gotowego stosu (I-2d, P-I) ---

def _seed_stos(con, *, reason=None, asserted="window"):
    """Stos + dwie klatki wejściowe + policzony rodowód — minimalny materiał panelu."""
    con.execute("INSERT INTO frame (id, sha1_data, kind, filetype, first_seen_at) "
                "VALUES (10, 'm10', 'master_light', 'xisf', ?)", (NOW,))
    con.execute("INSERT INTO header (frame_id, raw_json) VALUES (10, '{}')")
    con.execute("INSERT INTO location (frame_id, volume, path, present) "
                "VALUES (10, 'V', '/a/masterLight.xisf', 1)")
    con.execute("INSERT INTO integration (id, master_frame_id, created_at, degenerate, ambiguous, "
                "telescope_mismatch, unresolved_reason) VALUES (5, 10, ?, 0, 0, 0, ?)",
                (NOW, reason))
    if reason is None:
        for fid in (1, 2):
            con.execute("INSERT INTO integration_input (integration_id, input_frame_id, "
                        "asserted_by) VALUES (5, ?, ?)", (fid, asserted))
    con.commit()


def _zaznacz_frame(view, frame_id):
    """Zaznacz w tabeli wiersz danej klatki (przez model, nie przez piksele)."""
    view.refresh()
    for i, r in enumerate(view.model._rows):
        if isinstance(r, dict) and r.get("frame_id") == frame_id:
            view.table.selectRow(i)
            return True
    return False


def test_panel_rodowodu_pokazuje_zrodlo_pewnosci(view, gcon):
    """Panel mówi WPROST, na jakiej podstawie klatka jest w obrazie: „plik zeznał" vs „wynika
    z czasu". Bez tej różnicy rodowód wyglądałby jak wiedza pewna, a w większości nią nie jest."""
    _seed_stos(gcon, asserted="window")
    assert _zaznacz_frame(view, 10)
    view._toggle_panel("lineage")
    bar = view.lineage_bar
    assert bar.items.count() == 2
    assert "wynika z czasu" in bar.items.item(0).text()
    assert "Weszły 2 klatki" in bar.head.text()          # odmiana przez `t_plural` (wiz #15)


def test_panel_rodowodu_bez_wejsc_NIE_liczy_zera(view, gcon):
    """WIZYTACJA P1 #1: stos, którego rodowodu nie da się ustalić, dostawał nagłówek „Weszło
    0 klatek · 0.0 h" — twierdzenie, którego model NIE MA (obraz z czegoś powstał, tylko nie wiemy
    z czego). Dotyczyło 47 ze 128 stosów archiwum, czyli stanu najczęstszego.

    Nagłówek oddaje wtedy głos POWODOWI, bo to on mówi, którą naprawę wykonać; liczba i godziny
    znikają, a lista i przyciski nie zajmują pionu na treść, której nie będzie (wiz #6)."""
    _seed_stos(gcon, reason="degenerate_window")
    assert _zaznacz_frame(view, 10)
    view._toggle_panel("lineage")
    bar = view.lineage_bar
    assert bar.items.count() == 0
    assert "jedną klatkę" in bar.head.text()
    assert "0 klatek" not in bar.head.text() and "0.0 h" not in bar.head.text()
    # `isHidden` odwrócone, NIE `isVisible()`: to drugie jest fałszem także wtedy, gdy przodek
    # niepokazany (offscreen przed `show()`), więc twierdziłoby o schowaniu bez pokrycia.
    assert bar.items.isHidden() and bar.action_row.isHidden()


def test_bezimienny_stos_pokazuje_FOLDER_zamiast_pustki(gcon):
    """FIRSTHAND ZDZINIA 0808: „nie widzę napisu LMC ani IC443". I nie mógł — kubełek daje 18
    wierszy, a nazwy plików generuje WBPP, więc sześć stosów LMC i jeden IC443 czytają się
    identycznie (`masterLight_BIN-1_…_EXPOSURE-….xisf`). Tożsamość siedzi WYŁĄCZNIE w folderze.

    Test pinuje trzy rzeczy naraz, bo każda z nich osobno dałaby się zepsuć bez czerwieni:
    folder WCHODZI dla stosu bez nazwy · folder ma być DZIADKIEM, nie rodzicem (rodzic to `master`
    u wszystkich, więc nie rozróżnia niczego) · nazwa PRAWDZIWA wygrywa z podpowiedzią i nie dostaje
    nawiasów, żeby dwa różne twierdzenia nie wyglądały tak samo."""
    from horreum.gui.grid import _obj_label

    stos = dict(kind="master_light", object_canon=None, object_raw=None,
                path=r"R:\!!ASTROFOTO\OBIEKTY_DNG\A7R3_105_LMC\master\masterLight_BIN-1.xisf")
    assert _obj_label(stos) == "⟨A7R3_105_LMC⟩"

    nazwany = dict(stos, object_canon="LMC")
    assert _obj_label(nazwany) == "LMC"

    light = dict(kind="light", object_canon=None, object_raw=None,
                 path=r"R:\ASTRO_\LIGHTS\IC443\portable\20190110_DSC5559.dng")
    assert _obj_label(light) == "", "light ma własną drogę (szczebel ścieżki S2)"

    # Kolumny `kind`/`path` nie wchodzą z KAŻDEGO zapytania gridu — brak nie ma prawa wywalić
    # renderu (dlatego `_derive` podaje słownik, nie surowy `sqlite3.Row`).
    assert _obj_label({"object_canon": None, "object_raw": None}) == ""


def test_panel_nie_powtarza_powodu_ktory_zwietrzal(view, gcon):
    """FIRSTHAND ZDZINIA 0808, pkt 9: panel twierdził „obraz nie ma rozpoznanego obiektu", gdy
    kolumna Obiekt W TYM SAMYM OKNIE pokazywała `IC443`. Sprzeczności user nie ma prawa rozstrzygać
    domysłem.

    Mechanizm nie był zepsuty — `unresolved_reason` to zapis z ostatniego przebiegu rodowodu,
    a obiekt nadaje się GESTEM między przebiegami. Zepsute było zdanie: powtarzało stary werdykt
    jako bieżący. Odtąd panel mówi, że jego zapis jest starszy niż zmiana, i gdzie go odświeżyć."""
    _seed_stos(gcon, reason="no_object")
    assert _zaznacz_frame(view, 10)
    view._toggle_panel("lineage")
    assert "nie ma rozpoznanego obiektu" in view.lineage_bar.head.text()

    # Gest człowieka MIĘDZY przebiegami — tak jak przy „Napraw nagłówek…"/„Przypisz obiekt…".
    oid = gcon.execute(
        "INSERT INTO object(canon, catalog, kind) VALUES ('IC443', 'catalog', 'deep_sky')").lastrowid
    gcon.execute("UPDATE frame SET object_id = ? WHERE id = 10", (oid,))
    gcon.commit()
    view._refresh_lineage()
    tekst = view.lineage_bar.head.text()
    assert "nieaktualny" in tekst, "panel ma przyznać, że jego zapis zwietrzał"
    assert "nie ma rozpoznanego obiektu" not in tekst, "stary werdykt nie ma prawa wrócić jako bieżący"


def _seed_stos_z_rozjazdem(gcon):
    """Drugi stos: MA wejście i MA rozjazd teleskopu, więc panel stawia przy nim ostrzeżenie.
    Istnieje po to, żeby dało się zmierzyć, czy ostrzeżenie zostaje przy SWOIM obrazie."""
    raw = {"IMAGETYP": "Master Light", "EXPTIME": 300.0,
           "DATE-OBS": "2023-05-01T20:00:00", "DATE-END": "2023-05-01T23:00:00"}
    gcon.execute("INSERT INTO frame (id, sha1_data, kind, filetype, object_id, filter_canon, "
                 "first_seen_at) VALUES (11, 'm11', 'master_light', 'xisf', 7, 'Ha', ?)", (NOW,))
    gcon.execute("INSERT INTO header (frame_id, raw_json, date_obs, exptime) "
                 "VALUES (11, ?, '2023-05-01T20:00:00', 300.0)", (json.dumps(raw),))
    gcon.execute("INSERT INTO location (frame_id, volume, path, present) "
                 "VALUES (11, 'V', '/a/inny.xisf', 1)")
    gcon.execute("INSERT INTO integration (id, master_frame_id, created_at, degenerate, ambiguous, "
                 "telescope_mismatch, unresolved_reason) VALUES (6, 11, ?, 0, 0, 1, NULL)", (NOW,))
    gcon.execute("INSERT INTO integration_input (integration_id, input_frame_id, asserted_by, "
                 "excluded) VALUES (6, 20, 'window', 0)")
    gcon.commit()


def _seed_stos_z_kandydatami(gcon, *, reason="degenerate_window", filetype="fits"):
    """Stos z oknem ZDEGENEROWANYM + materiał dwóch nocy — minimalny materiał trybu propozycji.
    Master bez configu, więc oś teleskopu nie zawęża (jak u 83 z 85 masterów archiwum).

    `filetype='raw'` odtwarza populację 6× LMC: kandydaci SĄ, ale obraz nie ma wskazanego
    odniesienia czasu, więc nie da się powiedzieć, do której NOCY należą."""
    gcon.execute("INSERT INTO object (id, canon, catalog, kind) "
                 "VALUES (7, 'M51', 'catalog', 'deep_sky')")
    raw = {"IMAGETYP": "Master Light", "EXPTIME": 300.0,
           "DATE-OBS": "2023-04-21T20:00:00", "DATE-END": "2023-04-21T20:05:00"}
    gcon.execute("INSERT INTO frame (id, sha1_data, kind, filetype, object_id, filter_canon, "
                 "first_seen_at) VALUES (10, 'm10', 'master_light', 'xisf', 7, 'Ha', ?)", (NOW,))
    gcon.execute("INSERT INTO header (frame_id, raw_json, date_obs, exptime) "
                 "VALUES (10, ?, '2023-04-21T20:00:00', 300.0)", (json.dumps(raw),))
    gcon.execute("INSERT INTO location (frame_id, volume, path, present) "
                 "VALUES (10, 'V', '/a/masterLight.xisf', 1)")
    gcon.execute("INSERT INTO integration (id, master_frame_id, created_at, degenerate, ambiguous, "
                 "telescope_mismatch, unresolved_reason) VALUES (5, 10, ?, 1, 0, 0, ?)",
                 (NOW, reason))
    for fid, czas in ((20, "2023-04-21T20:00:00"), (21, "2023-04-21T21:00:00"),
                      (22, "2023-04-25T20:00:00")):
        gcon.execute("INSERT INTO frame (id, sha1_data, kind, filetype, object_id, filter_canon, "
                     "first_seen_at) VALUES (?, ?, 'light', ?, 7, 'Ha', ?)",
                     (fid, f"s{fid}", filetype, NOW))
        gcon.execute("INSERT INTO header (frame_id, raw_json, date_obs, exptime) "
                     "VALUES (?, '{}', ?, 300.0)", (fid, czas))
    gcon.commit()


def test_panel_proponuje_material_gdy_okno_nie_umialo_wybrac(view, gcon):
    """Poz. 4 etapu 3 stała się WYKONALNA (0808): do tej zmiany panel przy 35 stosach bez rodowodu
    tylko tłumaczył, dlaczego milczy — lista wejść była pusta, więc wiersz z przyciskami chował się
    w całości i nie było czego potwierdzać. Teraz ten sam panel podaje materiał nocy obrazu."""
    _seed_stos_z_kandydatami(gcon)
    assert _zaznacz_frame(view, 10)
    view._toggle_panel("lineage")
    bar = view.lineage_bar
    assert not bar.night_row.isHidden() and not bar.action_row.isHidden()
    assert bar.combo_night.count() == 2
    assert bar.combo_night.currentData() == "2023-04-21"          # otwiera się na NOCY OBRAZU
    assert bar.items.count() == 2
    assert "nie wiem" in bar.head.text().lower()                  # powód zostaje na wierzchu


def test_przelaczenie_nocy_przerysowuje_liste_bez_pytania_bazy(view, gcon):
    """Rdzeń oddaje WSZYSTKIE noce naraz, więc combo pracuje z pamięci. Zapytanie per przełączenie
    chodziłoby po całym materiale obiektu przy każdym kliknięciu — a to ten sam gest, którym
    człowiek przegląda listę w tę i we w tę."""
    _seed_stos_z_kandydatami(gcon)
    assert _zaznacz_frame(view, 10)
    view._toggle_panel("lineage")
    bar = view.lineage_bar
    przed = gcon.total_changes
    bar.combo_night.setCurrentIndex(1)
    assert bar.combo_night.currentData() == "2023-04-25"
    assert bar.items.count() == 1
    assert gcon.total_changes == przed, "przełączenie nocy nie ma prawa niczego zapisać"


def test_kandydaci_RAW_bez_zegara_dostaja_ZDANIE_I_KLIKALNY_GEST(view, gcon):
    """Bramka pakietu 3a (0808), zarzut BLOKUJĄCY — zmierzony na żywym archiwum na 6 z 35 obrazów
    kubełka (6× LMC, po 36 kandydatów każdy).

    Panel mówił im „Archiwum nie ma ani jednej klatki tego obiektu o zgodnym filtrze i ekspozycji",
    co było NIEPRAWDĄ: klatki stały w archiwum i przechodziły każdą oś, a wypadały wyłącznie
    na braku zegara obrazu. Recepta na to istnieje (gest odniesienia), ale przycisk był
    STRUKTURALNIE nieklikalny — jego warunek pytał o powód `offset_unknown`, którego stos
    o zdegenerowanym oknie nie dostanie NIGDY (`stacks._plan` kończy wcześniej).
    Czyli: cicha strata i stan bez wyjścia naraz."""
    _seed_stos_z_kandydatami(gcon, filetype="raw")
    assert _zaznacz_frame(view, 10)
    view._toggle_panel("lineage")
    bar = view.lineage_bar
    assert bar.items.count() == 0, "bez zegara nie umiemy umieścić ich w nocy — i to zostaje"
    nota = bar.note.full_text()
    assert "nie znam zegara" in nota, f"panel ma nazwać PRZYCZYNĘ pustki, a mówi: {nota!r}"
    assert "3" in nota, "zdanie ma nieść LICZBĘ kandydatów — bez niej nie widać stawki"
    assert "nie ma ani jednej klatki" not in nota, "to zdanie było fałszem"
    assert not bar.btn_offset.isHidden() and bar.btn_offset.isEnabled(), \
        "jedyna recepta musi być klikalna — inaczej ekran nie ma wyjścia"


def test_ostrzezenie_NIE_PRZECIEKA_z_poprzedniego_obrazu(view, gcon):
    """Bramka pakietu 3a (0808): gałąź propozycji kończy się `return`, więc omijała zapis
    ostrzeżenia — i panel nowego obrazu nosił ostrzeżenie POPRZEDNIEGO („⚠ obraz zapisał inny
    teleskop niż jego klatki") o cudzym pliku. Etykieta była realnie widoczna, nie tylko
    wypełniona, więc człowiek dostawał receptę naprawy karty dla obrazu, który jej nie potrzebuje."""
    _seed_stos_z_kandydatami(gcon)
    _seed_stos_z_rozjazdem(gcon)
    view.refresh()
    assert _zaznacz_frame(view, 11)                 # obraz Z ostrzeżeniem
    view._toggle_panel("lineage")
    bar = view.lineage_bar
    assert bar.warn.full_text(), "obraz 11 ma rozjazd teleskopu — ostrzeżenie ma stać"

    assert _zaznacz_frame(view, 10)                 # obraz BEZ ostrzeżenia, w trybie propozycji
    # Zmiana zaznaczenia odświeża panel przez DEBOUNCE (`_date_timer`, grid.py) — w teście
    # offscreen pętla zdarzeń nie chodzi, więc domykamy takt jawnie. To ta sama funkcja,
    # do której w aplikacji dochodzi timer.
    view._refresh_lineage()
    assert bar.combo_night.count(), "obraz 10 ma być w trybie propozycji (inaczej test nie mierzy)"
    assert bar.warn.full_text() == "", "ostrzeżenie należało do obrazu 11"
    assert bar.warn.isHidden(), "i nie ma prawa zostać na ekranie"


def test_pusta_noc_obrazu_zostaje_na_ekranie_z_receptą(view, gcon):
    """Pomiar 5 stosów `no_candidates`: obraz mówi o nocy, w której archiwum nie ma nic. Pusta noc
    ZOSTAJE pierwsza i mówi wprost, że materiał leży gdzie indziej — bez tego człowiek nie odróżnia
    „program nie zrozumiał, o co pytam" od „tej nocy naprawdę nic nie ma"."""
    _seed_stos_z_kandydatami(gcon, reason="no_candidates")
    gcon.execute("UPDATE header SET date_obs = '2023-04-30T20:00:00', "
                 "raw_json = ? WHERE frame_id = 10",
                 (json.dumps({"IMAGETYP": "Master Light", "EXPTIME": 300.0,
                              "DATE-OBS": "2023-04-30T20:00:00",
                              "DATE-END": "2023-04-30T20:05:00"}),))
    gcon.commit()
    assert _zaznacz_frame(view, 10)
    view._toggle_panel("lineage")
    bar = view.lineage_bar
    assert bar.combo_night.currentData() == "2023-04-30" and bar.items.count() == 0
    assert not bar.night_row.isHidden() and bar.action_row.isHidden()
    assert "wybierz inną noc" in bar.note.full_text()


def test_potwierdzenie_propozycji_domyka_stos_i_zdejmuje_go_z_kubelka(view, gcon):
    """CAŁA DROGA poz. 4 w jednym teście: propozycja → werdykt ręki → obraz ma rodowód → wypada
    z kubełka Porządków. Ostatni człon nie jest ozdobą: werdykt ręki ma rangę najwyższą, więc
    kolejny przebieg zostawia stos nietknięty RAZEM z zapisanym powodem — bez członu „wejścia
    wietrzą powód" obraz wracałby do kubełka po każdym przeliczeniu."""
    _seed_stos_z_kandydatami(gcon)
    assert 10 in queries.lineage_pending_frame_ids(gcon)
    assert _zaznacz_frame(view, 10)
    view._toggle_panel("lineage")
    bar = view.lineage_bar
    bar.items.selectAll()
    bar._emit(False)                                              # „Potwierdź zaznaczone"

    rows = gcon.execute("SELECT input_frame_id, asserted_by, excluded FROM integration_input "
                        "WHERE integration_id = 5 ORDER BY input_frame_id").fetchall()
    assert [(r["input_frame_id"], r["asserted_by"], r["excluded"]) for r in rows] == [
        (20, "user", 0), (21, "user", 0)]
    assert "Weszły 2 klatki" in bar.head.text()
    assert bar.night_row.isHidden(), "obraz z rodowodem niczego już nie proponuje"
    assert 10 not in queries.lineage_pending_frame_ids(gcon)

    from horreum.stacks import run_stack_lineage
    run_stack_lineage(gcon, now=NOW, xml_reader=lambda _p: None)
    assert 10 not in queries.lineage_pending_frame_ids(gcon), \
        "przebieg zamraża powód przy chronionym rodowodzie — kubełek nie ma prawa go odzyskać"


def test_perspektywa_rodowodu_zaweza_grid_do_czekajacych(view, gcon):
    """0808: panel „Rodowód" umiał gest od I-2d, ale działał WYŁĄCZNIE z zaznaczenia jednej klatki
    — żeby trafić na 35 obrazów czekających na słowo, trzeba było przeklikać 128 stosów. Wiersz
    Porządków celuje w tę perspektywę, więc jej trim jest jedyną drogą od liczby do listy."""
    from horreum.gui.grid import PRESET_LINEAGE
    _seed_stos(gcon, reason="degenerate_window")
    view.apply_perspective(PRESET_LINEAGE)
    assert view._only_lineage is True
    assert set(view._frame_ids) == queries.lineage_pending_frame_ids(gcon) == {10}


def test_perspektywa_rodowodu_NIE_wysyla_do_zwietrzalego_powodu(view, gcon):
    """Ten sam predykat, co w panelu (`queries.lineage_reason_stale`) — i to jest cały sens jednego
    właściciela: gdy user nada nazwę ręką, obraz WYPADA z listy gestów, bo czeka już tylko na etap
    „Policz rodowód stosów". Dwie kopie reguły posłałyby go tam, gdzie panel mówi „nieaktualny"."""
    from horreum.gui.grid import PRESET_LINEAGE
    _seed_stos(gcon, reason="no_object")
    view.apply_perspective(PRESET_LINEAGE)
    assert set(view._frame_ids) == {10}

    oid = gcon.execute(
        "INSERT INTO object(canon, catalog, kind) VALUES ('IC443','catalog','deep_sky')").lastrowid
    gcon.execute("UPDATE frame SET object_id = ? WHERE id = 10", (oid,))
    gcon.commit()
    view.refresh()
    assert view._frame_ids == [], "powód zwietrzał — to robota etapu, nie ręki"


def test_perspektywa_rodowodu_mowi_o_sobie_i_przezywa_zapis(view, gcon):
    """Flaga perspektywy jest POZA drzewem filtra (jak `only_dups`), więc bez własnego członu pasek
    kryteriów milczałby o zawężeniu, a zapisana perspektywa wracałaby jako „wszystkie klatki" —
    cichy fałsz w obie strony. Serializacja i opis idą jednym ruchem z flagą."""
    from horreum.gui.grid import PRESET_LINEAGE
    _seed_stos(gcon, reason="degenerate_window")
    view.apply_perspective(PRESET_LINEAGE)
    assert "bez rodowodu" in view.sel_bar.criteria_label._full
    spec = {"only_dups": view._only_dups, "only_review": view._only_review,
            "only_vanished": view._only_vanished, "only_lineage": view._only_lineage,
            "only_superseded": view._only_superseded}
    assert spec["only_lineage"] is True and not any(
        v for k, v in spec.items() if k != "only_lineage")


def test_perspektywa_zastapione_zawęża_grid_i_opisuje_się_w_kryteriach(view, gcon):
    """Bliźniak testu wyżej dla flagi `only_superseded` (0809). Bramka 3a wskazała, że rodzina
    `only_*` ma konsumentów rozsianych po widoku (spec zapisu, pasek kryteriów, trim `_refresh`),
    a rozjechana enumeracja tych flag już raz wyprodukowała „Baza pusta" na pełnej bazie — więc
    każdy nowy brat potrzebuje własnego przebiegu, nie samego wpisu w słowniku presetów."""
    from horreum.gui.grid import PRESET_SUPERSEDED
    gcon.execute("UPDATE frame SET superseded_by = 2 WHERE id = 1")
    gcon.commit()

    view.apply_perspective(PRESET_SUPERSEDED)
    assert view._only_superseded is True
    assert "zastąpione" in view.sel_bar.criteria_label._full
    assert view._frame_ids == [1], "trim ma zostawić WYŁĄCZNIE klatkę zastąpioną"

    view.apply_perspective("Przegląd")
    assert view._only_superseded is False, "flaga ma gasnąć przy zmianie perspektywy"
    assert 1 in view._frame_ids, "zastąpiona ZOSTAJE w gridzie pełnym (F1) — znika z ROBOTY, nie z archiwum"


def test_tokeny_panelu_sa_LUSTREM_stalych_rdzenia():
    """Panel trzyma dwa powody jako literały (warstwa widżetów nie importuje rdzenia — izolacja §4),
    więc równość obu zapisów musi pilnować bramka. Bez niej zmiana tokenu w `stacks` zostawiłaby
    panel cicho ślepym: przycisk odniesienia przestałby się pokazywać, a nic by nie zaczerwieniło."""
    from horreum import stacks
    from horreum.gui.grid import REASON_NO_OBJECT_TOKEN, REASON_OFFSET_TOKEN

    assert REASON_NO_OBJECT_TOKEN == stacks.REASON_NO_OBJECT
    assert REASON_OFFSET_TOKEN == stacks.REASON_OFFSET_UNKNOWN


def test_gest_odniesienia_wchodzi_tylko_tam_gdzie_jest_pytaniem(view, gcon):
    """R2: przycisk „Wskaż odniesienie…" ma się pokazać przy powodzie `offset_unknown` i NIE
    pokazywać przy innym. Dla 121 masterów FITS/ASI zegar nie jest pytaniem, a przycisk
    sugerowałby problem tam, gdzie go nie ma."""
    _seed_stos(gcon, reason="degenerate_window")
    assert _zaznacz_frame(view, 10)
    view._toggle_panel("lineage")
    assert view.lineage_bar.btn_offset.isHidden()

    gcon.execute("UPDATE integration SET unresolved_reason = 'offset_unknown' WHERE id = 5")
    gcon.commit()
    view._refresh_lineage()
    assert not view.lineage_bar.btn_offset.isHidden()
    assert "odniesienie" in view.lineage_bar.btn_offset.text().lower()


def test_gest_odniesienia_zapisuje_i_zostawia_droge_powrotu(view, gcon):
    """Zapis idzie KLINGĄ (`repo.set_integration_offset`), a panel po nim NIE gaśnie: przycisk
    zostaje, niosąc wskazaną wartość — bo pierwsza pomyłka ręki nie ma być wieczna (ta sama
    lekcja, co przy zestawie w R1, gdzie zarzut bramki pakietu 3a nazwał dokładnie ten dług)."""
    _seed_stos(gcon, reason="offset_unknown")
    assert _zaznacz_frame(view, 10)
    view._toggle_panel("lineage")
    view.lineage_bar.offset_asked.emit(60)

    assert gcon.execute("SELECT utc_offset_min FROM integration WHERE id = 5").fetchone()[0] == 60
    assert gcon.execute("SELECT count(*) FROM event WHERE verb = 'integration.offset_set' "
                        "AND actor LIKE 'user:%'").fetchone()[0] == 1
    assert not view.lineage_bar.btn_offset.isHidden(), "droga powrotu ma zostać"
    assert "+1.0" in view.lineage_bar.btn_offset.text()


def test_gest_odniesienia_DOMYKA_SIE_sam(view, gcon):
    """FIRSTHAND ZDZINIA 0808: „podałem różnicę czasu i muszę teraz zmienić zakładkę na Dostawę
    i klikać button, który jest przy buttonie wyboru folderu — UX-owo to jest niezrozumiałe".

    Gest zmienia fakt, na którym stoi dobór wejść, więc dopóki rodowód się nie przeliczy, ekran
    pokazuje stan sprzed gestu. Akcja domykająca mieszkała na INNYM ekranie, w sekcji o wciąganiu
    plików z dysku — trzy kliknięcia i zmiana kontekstu za czynność, która jest drugą połową tej
    samej decyzji. Takt 3 (wzorzec „Napraw nagłówek…" → `run_stage('resolve')`) domyka ją na miejscu.

    Test pinuje OBIE gałęzie odmowy, bo zapis i przeliczenie to dwa różne zdarzenia: gdy silnik jest
    zajęty, gest ma powiedzieć prawdę o obu połówkach (zapisano — nie policzono, i dlaczego)."""
    _seed_stos(gcon, reason="offset_unknown")
    assert _zaznacz_frame(view, 10)
    view._toggle_panel("lineage")

    wolane = []
    view.run_stage_fn = lambda: wolane.append("stack_lineage") or None
    komunikaty = []
    view.status_message.connect(komunikaty.append)
    view.lineage_bar.offset_asked.emit(60)

    assert wolane == ["stack_lineage"], "gest ma sam uruchomić przeliczenie"
    assert gcon.execute("SELECT utc_offset_min FROM integration WHERE id = 5").fetchone()[0] == 60
    assert "liczę" in komunikaty[-1]

    view.run_stage_fn = lambda: "etap już biegnie"
    view.lineage_bar.offset_asked.emit(120)
    assert "NIE policzony" in komunikaty[-1] and "biegnie" in komunikaty[-1]
    assert gcon.execute("SELECT utc_offset_min FROM integration WHERE id = 5").fetchone()[0] == 120, \
        "odmowa przeliczenia nie ma prawa cofnąć ZAPISU — to dwa różne zdarzenia"


def test_gest_odniesienia_milknie_na_czas_przebiegu(view, gcon):
    """Ta sama bramka, co dla werdyktu ręki: etap pipeline'u pisze do `integration` w tle, więc
    druga powierzchnia zapisu tego samego stołu musi wtedy zamilknąć."""
    _seed_stos(gcon, reason="offset_unknown")
    assert _zaznacz_frame(view, 10)
    view._toggle_panel("lineage")
    view.lineage_bar.set_busy(True)
    assert not view.lineage_bar.btn_offset.isEnabled()
    view.lineage_bar.set_busy(False)
    assert view.lineage_bar.btn_offset.isEnabled()


def test_panel_bez_wejsc_nie_ostrzega_o_klatkach_ktorych_nie_ma(view, gcon):
    """WIZYTACJA P1 #2: „⚠ część TYCH klatek wchodzi też w inny obraz" świeciło przy PUSTEJ liście
    wejść — ostrzeżenie o czymś, czego na ekranie nie ma. Zmierzone: 42 z 47 stosów bez rodowodu
    miało jednocześnie `ambiguous=1`, więc to był stan typowy, nie brzegowy."""
    _seed_stos(gcon, reason="degenerate_window")
    gcon.execute("UPDATE integration SET ambiguous = 1, telescope_mismatch = 1 WHERE id = 5")
    gcon.commit()
    assert _zaznacz_frame(view, 10)
    view._toggle_panel("lineage")
    bar = view.lineage_bar
    assert bar.warn.full_text() == "" and bar.note.full_text() == ""
    assert "⚠" not in bar.head.text()


def test_werdykt_reki_na_wszystkich_zostawia_uczciwe_zero(view, gcon):
    """Odwrotna strona P1 #1: gdy CZŁOWIEK odrzuci wszystkie kandydatury, „weszło 0 klatek" jest
    PRAWDĄ i jego własną decyzją — nagłówek ma ją pokazać, a nie schować za powodem. Warunek stoi
    więc na POWODZIE (`unresolved_reason`), nie na samym zerze."""
    _seed_stos(gcon)
    assert _zaznacz_frame(view, 10)
    view._toggle_panel("lineage")
    for i in range(view.lineage_bar.items.count()):
        view.lineage_bar.items.item(i).setSelected(True)
    view.lineage_bar._emit(True)
    assert "0 klatek" in view.lineage_bar.head.text()
    assert view.lineage_bar.items.count() == 2          # wiersze zostają jako fakt „nie weszły"
    # TURA 2 #3: przy zerze to INFORMACJE są jedynym wyjaśnieniem zera — wspólny guard gasił je
    # dokładnie tam, gdzie są potrzebne. Gaśnie wyłącznie ostrzeżenie.
    assert "odrzuconych: 2" in view.lineage_bar.note.full_text()


def test_stos_z_powodem_pokazuje_odrzucone_wiersze_zeby_dalo_sie_cofnac(view, gcon):
    """TURA 2 #4: `_reconcile` omija werdykty ręki, więc integracja z POWODEM może mieć wiersze
    `user` przy `inputs == 0`. Gałąź powodu, która listy nie wypełniała, zabierała wtedy JEDYNĄ
    drogę cofnięcia własnej decyzji — panel pokazywał samo zdanie o powodzie."""
    _seed_stos(gcon)
    assert _zaznacz_frame(view, 10)
    view._toggle_panel("lineage")
    for i in range(view.lineage_bar.items.count()):
        view.lineage_bar.items.item(i).setSelected(True)
    view.lineage_bar._emit(True)                        # wszystkie odrzucone ręką
    gcon.execute("UPDATE integration SET unresolved_reason = 'no_window' WHERE id = 5")
    gcon.commit()
    view._refresh_lineage()

    bar = view.lineage_bar
    assert "nie podaje czasu" in bar.head.text()        # nagłówek oddaje głos powodowi
    assert bar.items.count() == 2 and not bar.items.isHidden()   # …a wiersze ZOSTAJĄ do cofnięcia
    assert not bar.action_row.isHidden()


def test_panel_rodowodu_wymaga_jednego_stosu(view, gcon):
    """Rodowód opisuje POJEDYNCZY obraz — inne zaznaczenie dostaje ZDANIE, nie pustkę.

    Od C3 (#6) „inne zaznaczenie" znaczy węziej niż przedtem: klatka NIEBA ma teraz własną
    odpowiedź (czym ją skalibrowano), więc zdanie „to nie ma rodowodu" należy się już tylko
    klatce KALIBRACYJNEJ — ona sama jest narzędziem i nie ma czym być skalibrowana."""
    _seed_stos(gcon)
    view._toggle_panel("lineage")
    assert "Zaznacz w tabeli" in view.lineage_bar.head.text()
    assert _zaznacz_frame(view, 3)                     # master_flat — narzędzie, nie cel kalibracji
    view._refresh_lineage()
    assert "klatka kalibracyjna" in view.lineage_bar.head.text()


def test_panel_pokazuje_os_kalibracji_dla_klatki_nieba(view, gcon):
    """C3 (#6): TEN SAM panel, druga odpowiedź. Zaznaczona klatka nieba pokazuje obie klasy
    (ciemność i pole) — także tę, której brakuje, bo „czego nie ma" jest tu połową odpowiedzi."""
    gcon.execute("INSERT INTO calibration (light_frame_id, master_frame_id, relation, "
                 "asserted_by, confidence) VALUES (1, 3, 'flat', 'horreum', 'recipe')")
    gcon.commit()
    assert _zaznacz_frame(view, 1)
    view._toggle_panel("lineage")
    bar = view.lineage_bar
    assert bar.items.count() == 2                       # dark + flat, zawsze obie klasy
    teksty = [bar.items.item(i).text() for i in range(2)]
    assert any("/a/f3.xisf" in t for t in teksty)       # powiązany master pokazuje SWOJĄ ścieżkę
    assert "1 z 2" in bar.head.text()
    # Werdykt ręki NIE ISTNIEJE w tej osi — `calibration` nie zna kolumny `excluded`, więc przyciski
    # nie mają w co trafić. Widoczne, ale bezczynne byłyby obietnicą bez pokrycia.
    assert bar.action_row.isHidden()


def test_panel_kalibracji_odroznia_nieliczone_od_braku(view, gcon):
    """Dwa różne „nie ma" wymagają dwóch różnych zdań: brak w archiwum kosztuje klatki, których
    nikt nie zrobił, a nieliczone powiązanie — jedno kliknięcie w Dostawie. Wspólny komunikat
    kazałby szukać winy tam, gdzie jej nie ma."""
    assert _zaznacz_frame(view, 1)
    view._toggle_panel("lineage")
    bar = view.lineage_bar
    assert "Skalibrowana: 0 z 2" in bar.head.text()
    assert bar.warn.full_text() == ""                   # nic nie czeka na przeliczenie — brak ⚠
    # POWÓD LUKI MUSI BYĆ NA EKRANIE, nie tylko w modelu — i ma być POWODEM TEJ klatki: light
    # fixture'u nie niesie nastawy, więc uczciwe jest „nie wiadomo, czego szukać", a nie zdanie
    # o pustym archiwum (dwie różne naprawy, dwa różne zdania).
    teksty = " ".join(bar.items.item(i).text() for i in range(bar.items.count()))
    assert "nie podaje pełnej nastawy" in teksty
    assert "grid.lin.cal" not in teksty                 # surowy klucz = literówka w tokenie


def test_panel_kalibracji_pokazuje_stan_nieliczony(view, gcon):
    """SEDNO tej osi: master JEST, powiązania nikt nie policzył. Bez dowodu na powierzchni ta gałąź
    była zaimplementowana i niewidziana — a to ona odróżnia „uruchom etap" od „kup klatki"."""
    # Materiał podajemy WPROST: derywację trzech stanów pokrywa `test_lineage.py` (rdzeń), a tu
    # sprawdzamy, czy powierzchnia je RENDERUJE — inaczej test badałby dwa razy to samo.
    stan = [{"relation": "dark", "master_frame_id": None, "master_path": None, "confidence": None,
             "asserted_by": None, "gap": None, "pending": True},
            {"relation": "flat", "master_frame_id": None, "master_path": None, "confidence": None,
             "asserted_by": None, "gap": None, "pending": True}]
    view._toggle_panel("lineage")
    view.lineage_bar.set_calibration(stan)
    teksty = " ".join(view.lineage_bar.items.item(i).text()
                      for i in range(view.lineage_bar.items.count()))
    assert "powiązania jeszcze nie policzono" in teksty
    assert "uruchom etap Rodowód" in view.lineage_bar.warn.full_text()


def test_panel_kalibracji_przyznaje_sie_do_znikniętego_mastera(view, gcon):
    """Powiązanie jest prawdziwe (tożsamość to `sha1_data`), ale plik zniknął — wiersz kończył się
    kropką i PUSTKĄ, a nagłówek dalej liczył go do „skalibrowana". Milczenie dokładnie tam, gdzie
    panel ma najwięcej do powiedzenia."""
    gcon.execute("INSERT INTO calibration (light_frame_id, master_frame_id, relation, "
                 "asserted_by, confidence) VALUES (1, 3, 'flat', 'horreum', 'recipe')")
    gcon.execute("UPDATE location SET present = 0 WHERE frame_id = 3")
    gcon.commit()
    assert _zaznacz_frame(view, 1)
    view._toggle_panel("lineage")
    teksty = " ".join(view.lineage_bar.items.item(i).text()
                      for i in range(view.lineage_bar.items.count()))
    assert "plik zniknął z dysku" in teksty and "#3" in teksty


def test_panel_kalibracji_nie_zgaduje_ktora_klatke_opisuje(view, gcon):
    """Zaznaczenie light + klatka kalibracyjna: panel NIE odpowiada o lighcie po cichu — nagłówek
    nie nazywa klatki, więc użytkownik nie miałby jak sprawdzić, o której z nich mowa (CAPTAIN)."""
    view.refresh()
    idx = {}
    for i, r in enumerate(view.model._rows):
        if isinstance(r, dict):
            idx[r.get("frame_id")] = i
    view.table.selectRow(idx[1])
    from PySide6.QtCore import QItemSelectionModel
    view.table.selectionModel().select(
        view.table.model().index(idx[3], 0),
        QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
    view._toggle_panel("lineage")
    assert "Zostaw jedną" in view.lineage_bar.head.text()


def test_przelaczenie_osi_wraca_z_zanizonym_sufitem_listy(view, gcon):
    """Oś kalibracji zaniża sufit listy do swoich DWÓCH wierszy (sufit 160 px zostawiał ~100 px
    pustki). Sufit musi więc wracać przy powrocie na oś stosów — inaczej obraz o 190 wejściach
    dostałby okno wysokości dwóch wierszy i przewijanie zamiast listy."""
    _seed_stos(gcon)
    assert _zaznacz_frame(view, 1)                      # klatka nieba → oś kalibracji
    view._toggle_panel("lineage")
    niski = view.lineage_bar.items.maximumHeight()
    assert niski < 160

    assert _zaznacz_frame(view, 10)                     # gotowy obraz → oś stosów
    view._refresh_lineage()
    assert view.lineage_bar.items.maximumHeight() == 160


def test_werdykt_reki_zapisuje_sie_i_odejmuje_od_godzin(view, gcon):
    """Odrzucenie ręką: wiersz ZOSTAJE (fakt „nie weszła"), ale wypada z liczby klatek i godzin —
    i przeżywa kolejny przebieg rodowodu (precedencja `user` w klindze)."""
    from horreum.stacks import run_stack_lineage
    _seed_stos(gcon)
    assert _zaznacz_frame(view, 10)
    view._toggle_panel("lineage")
    view.lineage_bar.items.item(0).setSelected(True)
    view.lineage_bar._emit(True)                        # „Odrzuć zaznaczone"

    row = gcon.execute("SELECT asserted_by, excluded FROM integration_input "
                       "WHERE input_frame_id = 1").fetchone()
    assert (row["asserted_by"], row["excluded"]) == ("user", 1)
    assert "Weszła 1 klatka" in view.lineage_bar.head.text()   # licznik panelu odjął odrzuconą
    assert view.lineage_bar.items.count() == 2          # …ale wiersz został na liście
    # ZAZNACZENIE PRZEŻYWA WERDYKT (wiz #8): bez tego cofnięcie własnej decyzji kosztowało
    # odszukanie tych samych wierszy od nowa, a lista jest przebudowywana ze stanu.
    assert view.lineage_bar.selected_frame_ids() == [1]

    run_stack_lineage(gcon, now=NOW, xml_reader=lambda _p: None)
    row2 = gcon.execute("SELECT asserted_by, excluded FROM integration_input "
                        "WHERE input_frame_id = 1").fetchone()
    assert (row2["asserted_by"], row2["excluded"]) == ("user", 1)   # automat nie cofnął ręki


def test_panel_odroznia_wariant_obrazu_od_realnego_wspoldzielenia(view, gcon):
    """Zmierzone na 128 realnych stosach: z 62 integracji oflagowanych jako „okno nierozłączne"
    **51 ma bliźniaka o IDENTYCZNYM zbiorze wejść** (to warianty tego samego obrazu: `_ast`,
    `_drizzle_1x`), a tylko 11 dzieli klatki częściowo. Jedno ostrzeżenie na oba przypadki
    krzyczałoby o niczym w 82% sytuacji — dlatego panel czyta `integ_hash`, nie samą flagę.

    RECENZJA #6 (zmierzone 17 ze 128): stary `elif` gasił ostrzeżenie SAMĄ obecnością bliźniaka,
    więc integracja mająca JEDNO I DRUGIE dostawała wyłącznie komunikat uspokajający. Predykaty są
    teraz rozłączne i pytają o dwie różne rzeczy, więc mogą wystąpić razem — a ostrzeżenie stoi na
    REALNYM współdzieleniu wiersza wejścia (`shared`), nie na nakładaniu się okien planu.

    Ostrzeżenie i informacja mają też RÓŻNE ROLE malowania (wiz #4): jedno żąda decyzji, drugie
    tylko tłumaczy obraz — wspólna szara nota zrównywała je ze sobą."""
    _seed_stos(gcon)
    gcon.execute("UPDATE integration SET ambiguous = 1, integ_hash = 'ZBIOR-A' WHERE id = 5")
    gcon.execute("INSERT INTO frame (id, sha1_data, kind, filetype, first_seen_at) "
                 "VALUES (11, 'm11', 'master_light', 'xisf', ?)", (NOW,))
    gcon.execute("INSERT INTO integration (id, master_frame_id, created_at, integ_hash, ambiguous) "
                 "VALUES (6, 11, ?, 'ZBIOR-A', 1)", (NOW,))
    gcon.execute("INSERT INTO integration_input (integration_id, input_frame_id, asserted_by) "
                 "VALUES (6, 1, 'window')")              # ta sama klatka w obu integracjach
    gcon.commit()
    assert _zaznacz_frame(view, 10)
    view._toggle_panel("lineage")
    bar = view.lineage_bar
    assert "inna wersja obrazu" in bar.note.full_text()
    assert bar.warn.full_text() == ""                    # ten sam zbiór ⇒ to wariant, nie kolizja

    gcon.execute("UPDATE integration SET integ_hash = 'ZBIOR-B' WHERE id = 6")   # inny zbiór
    gcon.commit()
    view._refresh_lineage()
    assert "⚠ część tych klatek" in bar.warn.full_text()
    assert bar.warn.property("role") == "warn"           # ostrzeżenie nie jest szarą notą
    assert "⚠" not in bar.note.full_text()


# ═════════════════════════ S2b — OŚ OBIEKTU NA ZAZNACZENIU (§4/14c a·f·g·j)


@pytest.fixture
def obj_view(qapp, tmp_path, monkeypatch):
    """FramesView nad bazą: 2 lighty ze ŚCIEŻKI (źródło słabe), 1 z NAGŁÓWKA, 1 dark."""
    from PySide6.QtCore import QSettings
    from horreum.gui.grid import FramesView
    monkeypatch.setattr(QSettings, "value", lambda self, k, d=None: d)
    monkeypatch.setattr(QSettings, "setValue", lambda self, k, v: None)
    con = db.open_db(str(tmp_path / "obj.db"))
    con.execute("INSERT INTO object(id, canon, catalog, kind) VALUES (5,'NGC6960','NGC','deep_sky')")
    for i, (kind, src) in enumerate([("light", "path"), ("light", "path"),
                                     ("light", "header"), ("dark", None)], start=1):
        con.execute("INSERT INTO frame(id, kind, filetype, sha1_data, first_seen_at, "
                    "object_id, object_source) VALUES (?,?, 'raw', ?, ?, ?, ?)",
                    (i, kind, f"sha{i}", NOW, 5 if src else None, src))
        con.execute("INSERT INTO header(frame_id, raw_json) VALUES (?, '{}')", (i,))
        con.execute("INSERT INTO location(frame_id, volume, path, present) VALUES (?,'V',?,1)",
                    (i, rf"R:\ASTRO_\LIGHTS\NGC6960\f{i}.ARW"))
    con.commit()
    v = FramesView(con, now_fn=lambda: NOW)
    yield v, con
    con.close()


def _zaznacz(view, frame_ids):
    """Zaznacz wiersze po KLATCE, nigdy po indeksie: grid sortuje i grupuje, więc `index(0)` bywa
    zupełnie inną klatką, niż wpisała fikstura. Pierwsza wersja tego helpera zaznaczała po pozycji
    i trafiała w darka — testy „przechodziły" na pustym geście."""
    from PySide6.QtCore import QItemSelectionModel
    sm = view.table.selectionModel()
    sm.clearSelection()
    chciane = set(frame_ids)
    for i, row in enumerate(view.model._rows):
        if isinstance(row, dict) and row.get("frame_id") in chciane:
            sm.select(view.model.index(i, 0),
                      QItemSelectionModel.Select | QItemSelectionModel.Rows)


def test_pasek_ma_JEDNA_kontrolke_osi_z_dwiema_pozycjami(obj_view):
    """§4/14c-j: pasek zyskuje JEDNĄ kontrolkę, nie dwa przyciski — siódmy i ósmy przewróciłyby go
    do drugiego rzędu. Etykiety z KLUCZA i18n, nie literałem."""
    v, _ = obj_view
    assert v.sel_bar.btn_object.menu() is not None
    from horreum.gui import i18n
    # WIDOCZNE pozycje: pula skrótu „ostatnio użyte" (R-S2b-12) żyje w tym samym menu, ale jest
    # ukryta, dopóki dziennik nie ma czego pokazać — stała pula zamiast dokładania akcji, bo
    # `deleteLater` na QAction wywalał Qt (bramka pakietu, zarzut 8).
    assert [a.text() for a in v.sel_bar.btn_object.menu().actions() if a.isVisible()] == [
        i18n.t("grid.sel.object_name"), i18n.t("grid.sel.object_clear")]


def test_puste_zaznaczenie_GASI_obie_pozycje(obj_view):
    """§4/14c-a: cel to WYŁĄCZNIE zaznaczenie; przy pustym gaśnie cała kontrolka."""
    v, _ = obj_view
    v.refresh()
    _zaznacz(v, [])
    v._update_count()
    assert not v.sel_bar.act_name.isEnabled() and not v.sel_bar.act_clear.isEnabled()
    assert not v.sel_bar.btn_object.isEnabled()


def test_gest_przy_PUSTYM_zaznaczeniu_NIE_pisze_ani_jednego_wiersza(obj_view):
    """FALSYFIKATOR §4/14c-a woła SLOT, nie przycisk: klik w wyszarzony przycisk przeszedłby
    trywialnie i bramka nie mogłaby się zaczerwienić. Wygaszenie to PIERWSZA linia, guard w slocie
    DRUGA — i to ta druga jest tu dowodzona."""
    v, con = obj_view
    v.refresh()
    _zaznacz(v, [])
    przed = con.execute("SELECT count(*) FROM event").fetchone()[0]
    v._on_object_clear()
    v._on_object_name()
    assert con.execute("SELECT count(*) FROM event").fetchone()[0] == przed
    assert con.execute("SELECT count(*) FROM frame WHERE object_source = 'user_cleared'"
                       ).fetchone()[0] == 0


def test_cofniecie_z_paska_rusza_sciezke_a_naglowek_ZOSTAJE(obj_view):
    """§4/14c-e na POWIERZCHNI (klinga ma swój dom w `test_object_gesture`): zaznaczenie ze wszystkim
    naraz — dwie klatki ze ścieżki, jedna z nagłówka, jeden dark."""
    v, con = obj_view
    v.refresh()
    _zaznacz(v, [1, 2, 3, 4])
    v._on_object_clear()
    zrodla = dict(con.execute(
        "SELECT COALESCE(object_source,'—'), count(*) FROM frame GROUP BY 1").fetchall())
    assert zrodla == {"user_cleared": 2, "header": 1, "—": 1}


def _dodaj_stos(con, fid, src="user"):
    """Gotowy obraz z obiektem nadanym ręką — dokładnie ta klatka, którą D-OW-7 wpuściło pod gest."""
    con.execute("INSERT INTO frame(id, kind, filetype, sha1_data, first_seen_at, "
                "object_id, object_source) VALUES (?, 'master_light', 'xisf', ?, ?, 5, ?)",
                (fid, f"sha-stos{fid}", NOW, src))
    con.execute("INSERT INTO header(frame_id, raw_json) VALUES (?, '{}')", (fid,))
    con.commit()


def test_D_OW_7_gotowy_obraz_ODBLOKOWUJE_pozycje_Cofnij(obj_view):
    """PIN READ-MODELU, KTÓRY OTWIERA D-OW-7 W GUI — jedyna zmiana wpuszczająca stos pod „Cofnij"
    po stronie POWIERZCHNI (`queries.selection_object_state`: `stacks` przestało być `elif`-em
    wykluczającym klatkę z dalszych pytań).

    Wszystkie pozostałe bramki D-OW-7 jadą KLINGĄ (`repo.clear_object_assignment`), a klinga
    pomijania stosów nigdy nie miała — więc przywrócenie `elif` w read-modelu zostawiało cały
    komplet zielony, a w aplikacji pozycja „Cofnij" była przy stosie wygaszona. To ta sama figura,
    co „człon lustrzany jadący inną gałęzią kodu niż chroniona".

    Falsyfikator: zamień `if r["kind"] == "master_light"` z powrotem na `elif` przed testem
    `CLEARABLE_OBJECT_SOURCES` → `clearable` spada do 0 i `act_clear` gaśnie."""
    v, con = obj_view
    _dodaj_stos(con, 10)
    v.refresh()
    _zaznacz(v, [10])
    v._update_count()

    stan = queries.selection_object_state(con, [10])
    assert (stan["lights"], stan["stacks"], stan["clearable"]) == (1, 1, 1)
    assert v.sel_bar.act_clear.isEnabled()          # …i pozycja jest REALNIE klikalna
    assert v.sel_bar.btn_object.isEnabled()

    # …a gest wykonany przez SLOT naprawdę zdejmuje nazwę ze stosu i mówi, że jej dotknął
    msgs = []
    v.status_message.connect(msgs.append)
    v._on_object_clear()
    assert con.execute("SELECT object_source FROM frame WHERE id = 10").fetchone()[0] == "user_cleared"
    assert "w tym gotowy obraz: 1" in msgs[-1]      # JEDEN stos -> liczba pojedyncza


def test_licznik_stosow_NIE_sklei_sie_z_klatka_ktora_nie_miala_czego_cofac(obj_view):
    """R-S2b-5 nie wróciło TYLNYMI DRZWIAMI, a nowy człon mówi prawdę o przyczynie (wizytacja S3).

    Zaznaczenie: stos do cofnięcia + stos BEZ obiektu + light z nagłówka. Trzy różne fakty i trzy
    różne człony zdania — do S3 dwa ostatnie schodziły do jednego („z nagłówka/regionu: 2"),
    czyli komunikat mówił o nagłówku przy klatce, która żadnego nie miała, i podsuwał receptę
    („napraw kartą"), której nie da się wykonać."""
    v, con = obj_view
    _dodaj_stos(con, 10)                                        # ma co cofać
    con.execute("INSERT INTO frame(id, kind, filetype, sha1_data, first_seen_at) "
                "VALUES (11, 'master_light', 'xisf', 'sha-stos11', ?)", (NOW,))
    con.execute("INSERT INTO header(frame_id, raw_json) VALUES (11, '{}')")
    con.commit()
    v.refresh()
    _zaznacz(v, [10, 11, 3])                                    # 3 = light z NAGŁÓWKA
    msgs = []
    v.status_message.connect(msgs.append)
    v._on_object_clear()

    assert "Cofnięto przypisanie na 1 z 3 klatek" in msgs[-1]
    assert "· z nagłówka/regionu: 1" in msgs[-1]                # klatka 3 — fakt z pliku
    assert "· nie było czego cofać: 1" in msgs[-1]              # klatka 11 — nie miała obiektu
    assert "· w tym gotowy obraz: 1" in msgs[-1]                # ze zmienionych, nie z pominiętych


def test_gest_odswieza_OS_OBIEKTU_sygnalem(obj_view):
    """§4/14c-f, człon czwartej powierzchni: kolejka przeglądu żyje w INNYM oknie, więc grid nie może
    jej odświeżyć wołaniem — i nie ma poznawać gospodarza. Sygnał leci TYLKO gdy coś zapisano."""
    v, _ = obj_view
    ile = []
    v.object_axis_changed.connect(lambda: ile.append(1))
    v.refresh()
    _zaznacz(v, [1, 2])
    v._on_object_clear()
    assert ile == [1]
    v._on_object_clear()                 # drugi raz: nic do cofnięcia ⇒ zero zapisu ⇒ zero sygnału
    assert ile == [1]


def test_kolejka_NIE_dostaje_nowego_kubelka_poza_czlonem_cofniecia(obj_view):
    """§4/14c-g: nagrobek NIE tworzy szóstego kubełka — klatka wraca do tego, w którym była, a jej
    partycja dalej się domyka. Falsyfikator: gdyby `user_cleared` wypadło z `review_frame_ids`,
    równanie partycji rozjechałoby się DOKŁADNIE o liczbę cofnięć.

    CZŁON COFNIĘCIA (S3/R-S2b-1) — do dziś ta bramka pinowała jego BRAK jako stan poprawny, choć
    własna nazwa go zapowiadała. Rozszczepienie idzie PO ŹRÓDLE wewnątrz kubełka: dwie liczby
    ROZŁĄCZNE, których suma zostaje tą samą populacją. Bez rozłączności byłby to kubełek i jego
    podzbiór, a partycja liczyłaby te klatki dwa razy."""
    v, con = obj_view
    v.refresh()
    _zaznacz(v, [1, 2])
    v._on_object_clear()
    q = queries.review_queue(con)
    assert (q["nameless_raw_count"], q["nameless_raw_cleared_count"]) == (0, 2)
    assert len(queries.review_frame_ids(con)) == 2


# ── adjudykacja recenzji diffu S2b: trzy zdania, które POWIERZCHNIA mówiła nieprawdziwie ──


def test_rozbicie_PER_FAKT_przezywa_odswiezenie(obj_view):
    """Zdanie po UDANYM geście musi być OSTATNIM, co pada — inaczej nikt go nie zobaczy.

    `refresh()` kończy się własnym `status_message` („Grid: N klatek…"), a odbiornikiem jest jeden
    `showMessage` paska stanu. Emisja przed odświeżeniem ginęła w tym samym obrocie pętli, więc
    liczniki per fakt widać było WYŁĄCZNIE wtedy, gdy gest niczego nie zapisał. Bramka pyta
    o KOLEJNOŚĆ, bo sama treść komunikatu przechodziła i przedtem."""
    v, _ = obj_view
    v.refresh()
    zdania = []
    v.status_message.connect(zdania.append)
    _zaznacz(v, [1, 2, 3, 4])
    v._on_object_clear()
    assert zdania, "gest w ogóle nie odezwał się do usera"
    assert "2" in zdania[-1] and "kalibracja" in zdania[-1]     # rozbicie, nie „Grid: N klatek"


def test_odmowa_konfliktu_podaje_PRAWDZIWA_liczbe_obiektow(obj_view, monkeypatch):
    """Komunikat odmowy liczył literałem „2", więc przy pięciu obiektach kazał zawęzić do dwóch —
    a po zawężeniu odmawiał tak samo. Recepta, której nie da się wykonać, jest gorsza od milczenia."""
    v, con = obj_view
    con.execute("INSERT INTO object(id, canon, catalog, kind) VALUES (6,'M42','M','deep_sky')")
    con.execute("UPDATE frame SET object_id = 6 WHERE id = 2")   # drugi obiekt, źródło dalej słabe
    con.commit()
    v.refresh()
    zdania = []
    v.status_message.connect(zdania.append)
    _zaznacz(v, [1, 2])
    v._on_object_name()
    assert "2 różnych obiektów" in zdania[-1]
    assert queries.selection_object_state(con, [1, 2])["conflict_n"] == 2


def test_okno_dostaje_LICZBE_DO_ZAPISANIA_i_kontekst_zaznaczenia(obj_view, monkeypatch):
    """Etykieta akcji obiecywała „Przypisz 8 klatek" i zapisywała 4: `frame_count` szło z długości
    ZAZNACZENIA, nie z tego, co gest ruszy. Do tego okno wchodziło z `object_raw=None`, więc
    opisywało zaznaczenie zdaniem kubełka RAW („bez nazwy w metadanych") — o klatkach, które nazwę
    MAJĄ. Bramka pyta o OBA parametry, bo jeden bez drugiego dalej kłamie."""
    v, _ = obj_view
    v.refresh()
    zapis = {}

    class _Fake:
        def __init__(self, con, *, object_raw, frame_count, selection=None, cleared_n=0,
                     preselect_canon=None, parent=None):
            zapis.update(frame_count=frame_count, selection=selection, cleared_n=cleared_n,
                         preselect_canon=preselect_canon)
            self.selected = None

        def exec(self):
            return 0

    monkeypatch.setattr("horreum.gui.grid.AssignObjectDialog", _Fake)
    _zaznacz(v, [1, 2, 3, 4])            # 2 ze ścieżki + 1 z nagłówka + dark
    v._on_object_name()
    assert zapis["frame_count"] == 2                     # tyle gest realnie ruszy, nie 4
    assert zapis["selection"]["n"] == 4                  # …a okno wie, ile zaznaczono
    assert zapis["selection"]["overwrite"] == 2          # …i ile nazw przemaluje


# ═════════════════════════ S3 — SZUKANIE PO NAZWACH (§4/9, obietnica §1)


def test_szukajka_facetu_znajduje_obiekt_po_DRUGIEJ_NAZWIE(obj_view):
    """Kryterium 9 end-to-end na realnym oknie: „Large Magellanic Cloud" (ze spacjami) zostawia
    na liście kubełek `LMC`, a resztę chowa.

    Bramka pyta o CAŁĄ DROGĘ, nie o predykat (ten ma swoje człony w `test_grid_core`): mapa musi
    wyjść z bazy (`queries.object_alias_index`), przejść przez `FramesView._reload_facet_rail`
    i dojechać do listwy kwargiem. Implementacja, która policzy dopasowanie poprawnie, ale zapomni
    dowieźć aliasów, przechodzi tamte człony i przewraca ten."""
    v, con = obj_view
    con.execute("INSERT INTO object(id, canon, catalog, kind) VALUES (7,'LMC',NULL,'own')")
    con.execute("INSERT INTO object_alias(alias_norm, object_id, source) "
                "VALUES ('LARGEMAGELLANICCLOUD', 7, 'curated')")
    con.execute("UPDATE frame SET object_id = 7, object_source = 'user' WHERE id = 3")
    con.commit()
    v.refresh()
    lw = v.facet_rail._lists["object"]
    etykiety = {lw.item(i).data(Qt.UserRole)[2] for i in range(lw.count())}
    assert {"LMC", "NGC6960"} <= etykiety                  # oba kubełki są na liście

    v.facet_rail.search.setText("Large Magellanic Cloud")
    widoczne = {lw.item(i).data(Qt.UserRole)[2] for i in range(lw.count())
                if not lw.item(i).isHidden()}
    assert widoczne == {"LMC"}


def test_szukajka_PRZEZYWA_odswiezenie_listwy(obj_view):
    """Mapa aliasów dojeżdża przy KAŻDYM `set_data`, a szukajka filtruje przy każdym znaku — gdyby
    `aliases=None` znaczyło „wyczyść", pierwszy refresh w środku pisania gasiłby drugie nazwy
    i wiersz znikałby userowi spod palca. `None` znaczy „bez zmian"."""
    v, con = obj_view
    con.execute("INSERT INTO object(id, canon, catalog, kind) VALUES (7,'LMC',NULL,'own')")
    con.execute("INSERT INTO object_alias(alias_norm, object_id, source) "
                "VALUES ('LARGEMAGELLANICCLOUD', 7, 'curated')")
    con.execute("UPDATE frame SET object_id = 7, object_source = 'user' WHERE id = 3")
    con.commit()
    v.refresh()
    v.facet_rail.search.setText("magellanic")
    lw = v.facet_rail._lists["object"]

    v.facet_rail.set_data({"object": [(7, "LMC", 1)]}, v.facet_rail.state())   # BEZ kwargu
    widoczne = {lw.item(i).data(Qt.UserRole)[2] for i in range(lw.count())
                if not lw.item(i).isHidden()}
    assert widoczne == {"LMC"}


# ═════════════════════════ P-K — EKRAN NIE MILCZY (F-1 · F-2 · R-S2b-7 · R-S2b-8)


def _grid_z_iloscia(qapp, tmp_path, monkeypatch, n):
    """FramesView nad bazą o ZADANEJ liczbie lightów — fikstura bramek wydajności."""
    from PySide6.QtCore import QSettings
    from horreum.gui.grid import FramesView
    monkeypatch.setattr(QSettings, "value", lambda self, k, d=None: d)
    monkeypatch.setattr(QSettings, "setValue", lambda self, k, v: None)
    con = db.open_db(str(tmp_path / "perf.db"))
    con.execute("INSERT INTO object(id, canon, catalog, kind) VALUES (5,'NGC6960','NGC','deep_sky')")
    con.executemany(
        "INSERT INTO frame(id, kind, filetype, sha1_data, first_seen_at, object_id, object_source) "
        "VALUES (?, 'light', 'raw', ?, ?, 5, 'path')",
        [(i, f"sha{i}", NOW) for i in range(1, n + 1)])
    con.executemany("INSERT INTO header(frame_id, raw_json) VALUES (?, '{}')",
                    [(i,) for i in range(1, n + 1)])
    con.executemany("INSERT INTO location(frame_id, volume, path, present) VALUES (?,'V',?,1)",
                    [(i, rf"R:\ASTRO_\LIGHTS\NGC6960\f{i}.ARW") for i in range(1, n + 1)])
    con.commit()
    return FramesView(con, now_fn=lambda: NOW), con


def test_update_count_NIE_WOLA_selectedRows_ANI_RAZU(qapp, tmp_path, monkeypatch):
    """R-S2b-7, bramka NIEZALEŻNA OD MASZYNY — liczy WYWOŁANIA, nie milisekundy.

    Defekt miał dokładną postać: `_update_count` chodził po zaznaczeniu DWA razy przez
    `QItemSelectionModel.selectedRows()`, a ta metoda woła `model.flags()` dla KAŻDEJ komórki
    zakresu i buduje `QModelIndex` per wiersz. Zmierzone na żywej kopii `pf4` (16 648 klatek,
    widżet POKAZANY): **2 071 ms** na jedno zdarzenie zaznaczenia, przy rubber-bandzie raz na
    ruch myszy. Po zejściu na zakresy: **2,0 ms**.

    Ta bramka pyta o PRZYCZYNĘ (zero wywołań), a bliźniacza niżej o SKUTEK (czas) — bo sam czas
    przepuszcza wariant wolny z innego powodu, a samo liczenie wywołań przepuściłoby wariant,
    który koszt przeniósł gdzie indziej."""
    v, con = _grid_z_iloscia(qapp, tmp_path, monkeypatch, 200)
    try:
        v.resize(1200, 800)
        v.show()
        QApplication.processEvents()
        v.table.selectAll()
        QApplication.processEvents()

        sm = v.table.selectionModel()
        wolania = []
        oryginal = sm.selectedRows
        monkeypatch.setattr(sm, "selectedRows", lambda *a: (wolania.append(1), oryginal(*a))[1])
        v._update_count()
        assert len(v._selected_data_rows()) == 200, "fikstura nie zaznaczyła całości"
        assert wolania == [], f"_update_count wołał selectedRows() {len(wolania)}× — kwadrat wrócił"
    finally:
        v.close()
        con.close()


def test_zaznaczenie_calosci_NIE_jest_kwadratowe_ASERCJA_CZASOWA(qapp, tmp_path, monkeypatch):
    """R-S2b-7 — bramka CZASOWA, bo strukturalna przepuszcza wariant wolny z innego powodu
    (lekcja z firsthandu 0804: „gdy naprawa ma wariant-pułapkę, bramka musi umieć odróżnić oba").

    WIDŻET MUSI BYĆ POKAZANY (`show()`), inaczej model zaznaczenia nie ma czego przeliczać
    i pomiar BRONI zepsutego kodu — ta sama ścieżka mierzyła 74 ms na widoku bez `show()`
    i 57,7 s na pokazanym.

    PRÓG WYZNACZONY POMIAREM, NIE NA OKO. Falsyfikator przebiegnięty przez podmianę
    `_selected_data_rows` na wariant sprzed naprawy, ta sama fikstura, ta sama maszyna:

        n=1000   nowa  1,8 ms   stara   36,9 ms
        n=2000   nowa  3,9 ms   stara   73,1 ms
        n=4000   nowa  7,8 ms   stara  146,9 ms

    Stąd n=4000 i próg **50 ms**: stara droga przekracza go 3× (147 ms), nowa ma pod nim 6×
    zapasu (7,8 ms). Pierwsza wersja tej bramki miała próg 300 ms i była OZDOBĄ — stara droga
    mieściła się w nim swobodnie, więc test przechodził niezależnie od implementacji."""
    import time
    v, con = _grid_z_iloscia(qapp, tmp_path, monkeypatch, 4000)
    try:
        v.resize(1200, 800)
        v.show()
        QApplication.processEvents()
        v.table.selectAll()
        QApplication.processEvents()

        t = time.perf_counter()
        v._update_count()
        dt = (time.perf_counter() - t) * 1000
        assert len(v._selected_data_rows()) == 4000, "fikstura nie zaznaczyła całości"
        assert dt < 50, f"_update_count przy pełnym zaznaczeniu: {dt:.0f} ms (kwadrat wrócił)"
    finally:
        v.close()
        con.close()


def test_traversal_zaznaczenia_ma_PARYTET_ze_stara_droga(obj_view):
    """R-S2b-7 — nowa droga karmi ZAPIS osi obiektu, więc równość ze starą musi być dowiedziona,
    nie założona. Przypadek graniczny jest jeden: zakresy zaznaczenia potrafią się NAKŁADAĆ
    (kontrakt Qt), a `selectedRows()` oddaje wiersze unikalne — bez dedup po stronie zakresów
    klatka wpadłaby do zapisu dwa razy.

    Kolejność zmienia się ŚWIADOMIE (klikanie → wiersze), więc bramka porównuje ZBIORY i długości;
    żaden z pięciu wołających na kolejności nie stoi."""
    from PySide6.QtCore import QItemSelection, QItemSelectionModel, QModelIndex
    v, _ = obj_view
    v.refresh()
    sm = v.table.selectionModel()
    m = v.model
    sm.clearSelection()
    for a, b in ((0, 2), (1, 3)):                     # DRUGI zakres nachodzi na pierwszy
        sm.select(QItemSelection(m.index(a, 0), m.index(b, m.columnCount(QModelIndex()) - 1)),
                  QItemSelectionModel.Select)

    stara = []
    for idx in sm.selectedRows():
        row = m._rows[idx.row()]
        if isinstance(row, dict) and "_group" not in row:
            stara.append(row["frame_id"])
    nowa = [r["frame_id"] for r in v._selected_data_rows()]

    assert len(nowa) == len(set(nowa)), "zakresy nachodzące zduplikowały klatkę"
    assert set(nowa) == set(stara) and len(nowa) == len(stara)


def test_wygaszona_kontrolka_osi_TLUMACZY_SIE_powodem(obj_view):
    """R-S2b-8: „wygaszony przycisk tłumaczy się SAM" to doktryna repo, złamana akurat tu —
    kontrolka „Obiekt ▾" gasła BEZ tooltipa, choć trzej gatujący sąsiedzi swoje mają.

    Cztery stany, cztery różne zdania — bo user ma się dowiedzieć, GDZIE ta nazwa się poprawia,
    a nie tylko że nie tutaj. Falsyfikator: gdyby powód liczył się jednym zdaniem dla wszystkich,
    ten test przewróciłby się na dowolnej parze."""
    from horreum.gui import i18n
    v, con = obj_view
    v.refresh()

    _zaznacz(v, [])
    v._update_count()
    assert not v.sel_bar.btn_object.isEnabled()
    assert v.sel_bar.btn_object.toolTip() == i18n.t("grid.sel.object_tip_empty")

    _zaznacz(v, [4])                                    # sam dark — klatek nieba ZERO
    v._update_count()
    assert v.sel_bar.btn_object.toolTip() == i18n.t("grid.sel.object_tip_no_lights")

    _zaznacz(v, [3])                                    # light z NAGŁÓWKA — poprawia się w pliku
    v._update_count()
    assert v.sel_bar.btn_object.toolTip() == i18n.t("grid.sel.object_tip_header")

    _dodaj_stos(con, 12, src="header")                  # sam gotowy obraz z nazwą z pliku
    v.refresh()
    _zaznacz(v, [12])
    v._update_count()
    assert v.sel_bar.btn_object.toolTip() == i18n.t("grid.sel.object_tip_stacks")

    _zaznacz(v, [1, 2])                                 # …a przy AKTYWNEJ mówi, ile gest ruszy
    v._update_count()
    assert v.sel_bar.btn_object.isEnabled()
    assert v.sel_bar.btn_object.toolTip() == i18n.t("grid.sel.object_tip_ready",
                                                    namable=2, clearable=2)


def test_tooltip_AKTYWNEJ_kontrolki_liczy_gotowe_obrazy(obj_view):
    """R-S3-8: powód `object_tip_stacks` broni wyłącznie zaznaczenia z SAMYCH stosów — tam gasi
    kontrolkę. Przy zaznaczeniu MIESZANYM nikt gotowych obrazów nie liczył, więc o tym, że gest
    ruszył 128 obrazów złożonych z tysięcy klatek, user dowiadywał się PO zapisie (człon
    `grid.sel.object_stacks` w zdaniu końcowym), a nie przed nim.

    Człon jedzie tym samym kluczem, co zdanie po geście — jedna fraza, jeden właściciel. Milczy
    przy zerze: „w tym gotowe obrazy: 0" mówiłoby o czymś, czego w zaznaczeniu nie ma."""
    from horreum.gui import i18n
    v, con = obj_view
    _dodaj_stos(con, 13, src="user")
    v.refresh()

    _zaznacz(v, [1, 2])                                 # same klatki nieba — człon MILCZY
    v._update_count()
    assert v.sel_bar.btn_object.toolTip() == i18n.t("grid.sel.object_tip_ready",
                                                    namable=2, clearable=2)

    _zaznacz(v, [1, 2, 13])                             # …a przy stosie w zaznaczeniu MÓWI
    v._update_count()
    stan = queries.selection_object_state(con, [1, 2, 13])
    assert stan["stacks"] == 1
    assert v.sel_bar.btn_object.toolTip() == (
        i18n.t("grid.sel.object_tip_ready", namable=stan["namable"], clearable=stan["clearable"])
        + i18n.t_plural("grid.sel.object_stacks", 1))


def test_faza_zajetosci_gridu_NIE_zjada_zdania_koncowego(obj_view):
    """F-1: faza dzieli kanał z raportem TYLKO tam, gdzie po niej pada zdanie końcowe. `refresh()`
    kończy się własnym „Grid: N klatek…", więc opis roboty MUSI zostać przykryty — inaczej
    wskaźnik zajętości kasowałby komunikat, po który user czekał (ta sama klasa, którą repo ma
    zapisaną jako „zdanie idzie PO odświeżeniu")."""
    from horreum.gui import i18n
    v, _ = obj_view
    zdania = []
    v.status_message.connect(zdania.append)
    v.refresh()
    assert i18n.t("busy.read_frames") in zdania, "faza w ogóle się nie odezwała"
    assert zdania[-1].startswith("Grid:"), f"faza przykryła zdanie końcowe: {zdania[-1]!r}"


def test_kursor_oczekiwania_WRACA_takze_po_wyjatku(qapp):
    """F-1: wyjątek w środku długiej operacji nie ma prawa zostawić aplikacji z klepsydrą —
    to byłby wskaźnik, który sam udaje zawieszenie. `finally` w `busy` jest jedyną obroną."""
    from horreum.gui import busy as busy_mod
    assert QApplication.overrideCursor() is None
    with pytest.raises(RuntimeError):
        with busy_mod.busy(lambda _t: None, "robota"):
            raise RuntimeError("bum")
    assert QApplication.overrideCursor() is None


# ═════════════════════════ R-S3-5 / R-S3-9 — LISTWA: STAN PUSTY, CZYSZCZENIE, TRAFIONY ALIAS


def _rail_z_obiektami(qapp, aliases=None):
    from horreum.gui.facets import FacetRail
    rail = FacetRail()
    rail.resize(260, 500)
    rail.show()
    counts = {"object": [(1, "LMC", 3), (2, "NGC7000", 5)],
              "filter": [], "kind": [], "telescope": [], "night": []}
    rail.set_data(counts, {}, aliases=aliases)
    qapp.processEvents()
    return rail


def _widoczne(lw):
    """Wiersze REALNE (bez placeholdera) i niepochowane — to, co user widzi jako wartości."""
    from PySide6.QtCore import Qt
    return [lw.item(i).text() for i in range(lw.count())
            if not lw.item(i).isHidden() and lw.item(i).data(Qt.UserRole) is not None]


def _placeholder(lw):
    from PySide6.QtCore import Qt
    for i in range(lw.count()):
        if lw.item(i).data(Qt.UserRole) is None:
            return lw.item(i)
    return None


def test_fraza_bez_trafien_ma_WIERSZ_zamiast_niemego_prostokata(qapp):
    """R-S3-5: fraza bez trafień zostawiała ~180 px pustki i nic nie mówiło, co się stało.

    Falsyfikator: usuń wywołanie `_set_empty_row` z `_filter_objects` → placeholder znika."""
    rail = _rail_z_obiektami(qapp)
    lw = rail._lists["object"]
    assert _placeholder(lw) is None                       # przy trafieniach wiersza NIE MA

    rail.search.setText("nic-takiego-nie-ma")
    qapp.processEvents()
    assert _widoczne(lw) == []
    ph = _placeholder(lw)
    assert ph is not None and "nic-takiego-nie-ma" in ph.text()

    rail.search.setText("")                               # i znika, gdy trafienia wracają
    qapp.processEvents()
    assert _placeholder(lw) is None and len(_widoczne(lw)) == 2
    rail.hide()


def test_grupa_pusta_przy_zawezeniu_tez_mowi_dlaczego(qapp):
    """R-S3-5, druga połowa: zawężenie do jednego obiektu opróżnia Filtr/Teleskop/Noc NARAZ —
    zmierzone cztery nieme prostokąty w jednym widoku. Placeholder nie jest własnością szukajki."""
    rail = _rail_z_obiektami(qapp)
    for facet in ("filter", "kind", "telescope"):
        ph = _placeholder(rail._lists[facet])
        assert ph is not None, f"pusta grupa {facet} nie mówi nic"
        assert ph.text()
    rail.hide()


def test_placeholder_NIE_JEST_klikalny(qapp):
    """Wiersz stanu pustego nie może wpaść w dispatch cyklu — nie niesie wartości facetu."""
    from PySide6.QtCore import Qt
    rail = _rail_z_obiektami(qapp)
    lw = rail._lists["object"]
    rail.search.setText("nic-takiego-nie-ma")
    qapp.processEvents()
    ph = _placeholder(lw)
    assert ph.flags() == Qt.NoItemFlags
    assert ph.data(Qt.UserRole) is None
    zlapane = []
    rail.facetsChanged.connect(zlapane.append)
    rail._on_item_clicked(ph)                             # gest wprost w placeholder
    assert zlapane == [], "klik w wiersz stanu pustego zmienił stan facetów"
    rail.hide()


def test_szukajka_ma_przycisk_czyszczenia(qapp):
    """R-S3-5: skasowanie frazy kosztowało Ctrl+A+Del zamiast jednego kliknięcia."""
    rail = _rail_z_obiektami(qapp)
    assert rail.search.isClearButtonEnabled()
    rail.hide()


def test_wiersz_trafiony_ALIASEM_tlumaczy_sie_w_tooltipie(qapp):
    """R-S3-9: wpisujesz „Large Magellanic Cloud", dostajesz `LMC` i nie wiesz dlaczego.

    Falsyfikator: przywróć `search_hit` zwracające `bool` → tooltip nie ma czego pokazać."""
    rail = _rail_z_obiektami(qapp, aliases={"LMC": {"LARGEMAGELLANICCLOUD"}})
    lw = rail._lists["object"]
    rail.search.setText("Large Magellanic Cloud")
    qapp.processEvents()
    assert _widoczne(lw) == ["LMC"]
    tip = lw.item(0).toolTip()
    assert "LARGEMAGELLANICCLOUD" in tip

    rail.search.setText("LMC")                            # trafienie WŁASNĄ nazwą się nie tłumaczy
    qapp.processEvents()
    assert "LARGEMAGELLANICCLOUD" not in lw.item(0).toolTip()
    rail.hide()


# ═════════════════════════ R-S3-6 — ŚCIEŻKA KLAWIATURY


def test_enter_w_szukajce_bierze_PIERWSZE_trafienie(qapp):
    """R-S3-6: fraza tylko chowała wiersze — wybór i tak wymagał myszy (3 interakcje zamiast 2).

    Falsyfikator: rozłącz `returnPressed` → stan facetów zostaje pusty."""
    rail = _rail_z_obiektami(qapp)
    rail.search.setText("NGC7000")
    qapp.processEvents()
    zlapane = []
    rail.facetsChanged.connect(zlapane.append)
    rail.search.returnPressed.emit()
    assert zlapane and zlapane[-1]["object"]["in"] == [[2, "NGC7000"]]
    rail.hide()


def test_enter_bez_trafien_NIE_ROBI_NIC(qapp):
    """Fraza bez trafień nie ma czego potwierdzić — Enter nie może wziąć wiersza stanu pustego."""
    rail = _rail_z_obiektami(qapp)
    rail.search.setText("nic-takiego-nie-ma")
    qapp.processEvents()
    zlapane = []
    rail.facetsChanged.connect(zlapane.append)
    rail.search.returnPressed.emit()
    assert zlapane == []
    rail.hide()


def test_focus_search_zaznacza_dotychczasowa_fraze(qapp):
    """Ctrl+F woła `focus_search`: kursor w polu, stara fraza ZAZNACZONA (pisanie ją zastępuje)."""
    rail = _rail_z_obiektami(qapp)
    rail.search.setText("LMC")
    rail.focus_search()
    qapp.processEvents()
    assert rail.search.hasFocus()
    assert rail.search.selectedText() == "LMC"
    rail.hide()


# ═════════════════════════ R-S2b-11 / R-S2b-12 — PASEK ZBIORÓW: JEDEN CZASOWNIK, SKRÓT


def test_kontrolka_obiektu_ma_JEDEN_chevron_i_rowna_wysokosc(qapp):
    """R-S2b-11: tekst niósł własne „▾" obok natywnego wskaźnika `InstantPopup` (dwa chevrony),
    a `QToolButton` wychodził o 1 px niższy od sześciu sąsiadów-`QPushButton`.

    Falsyfikatory: wróć do „Obiekt ▾" → pierwsza asercja; zdejmij `setFixedHeight` → druga."""
    from horreum.gui.grid import SelectionBar
    bar = SelectionBar()
    bar.show()
    qapp.processEvents()
    assert "▾" not in bar.btn_object.text()
    assert bar.btn_object.height() == bar.btn_save.height()
    bar.close()


def test_jedna_robota_JEDEN_czasownik(qapp):
    """R-S2b-11: ta sama sprawa nazywała się „Nazwij zaznaczenie…", „Przypisz obiekt", „Przypisz
    N klatek" i „Przypisz obiekt…". Para gest↔cofnięcie musi mówić jednym czasownikiem."""
    from horreum.gui import i18n
    i18n.set_lang("pl")
    czasownik = "Przypisz"
    assert i18n.t("grid.sel.object_name").startswith(czasownik)      # menu Zbiorów
    assert i18n.t("assign.title").startswith(czasownik)              # tytuł okna
    assert i18n.t("object.assign_btn").startswith(czasownik)         # kolejka przeglądu
    assert i18n.t_plural("assign.accept_btn", 3).startswith(czasownik)   # akcept
    assert i18n.t("grid.sel.object_clear") == "Cofnij przypisanie"   # …i jego cofnięcie


def _pozycje_skrotu(bar):
    """WIDOCZNE pozycje skrótu — pula jest stała, nadmiar tylko się chowa."""
    return [a for a in bar.btn_object.menu().actions()
            if a.isVisible() and a.text().startswith("→")]


def test_skrot_ostatnio_uzytych_niesie_KOMPLET_pol(qapp):
    """R-S2b-12: „te klatki to znowu NGC6960" kosztowało 5 interakcji, spada do 2.

    Pozycja skrótu musi wieźć `catalog` i `kind` razem z kanonem: klinga INSERTuje obiekt, gdy
    kanon jest nowy, więc sam string zostawiłby zapis bez pól, których wymaga schemat.

    Falsyfikator: zawęź sygnał do samego kanonu → asercja o krotce czerwienieje."""
    from horreum.gui.grid import SelectionBar
    bar = SelectionBar()
    bar.set_object_actions(namable=3, clearable=0)
    bar.set_recent_objects([{"canon": "NGC6960", "catalog": "NGC", "kind": "deep_sky"},
                            {"canon": "LMC", "catalog": None, "kind": "own"}])
    zlapane = []
    bar.objectRecentPicked.connect(lambda *a: zlapane.append(a))
    pozycje = _pozycje_skrotu(bar)
    assert [a.text() for a in pozycje] == ["→ NGC6960", "→ LMC"]
    pozycje[0].trigger()
    assert zlapane == [("NGC6960", "NGC", "deep_sky")]
    bar.close()


def test_skrot_gasnie_razem_z_akcja_ktora_skraca(qapp):
    """Skrót nie może omijać bramki, którą stoi „Przypisz obiekt…" — puste zaznaczenie gasi oba."""
    from horreum.gui.grid import SelectionBar
    bar = SelectionBar()
    bar.set_object_actions(namable=0, clearable=0)          # nie ma czego nazwać
    bar.set_recent_objects([{"canon": "NGC6960", "catalog": "NGC", "kind": "deep_sky"}])
    pozycje = _pozycje_skrotu(bar)
    assert pozycje and not any(a.isEnabled() for a in pozycje)
    bar.close()


def test_lista_skrotu_przebudowuje_sie_a_nie_ROSNIE(qapp):
    """Pozycje powstają na nowo przy każdym pokazaniu menu — inaczej doklejałyby się w nieskończoność."""
    from horreum.gui.grid import SelectionBar
    bar = SelectionBar()
    bar.set_object_actions(namable=3, clearable=0)
    for _ in range(3):
        bar.set_recent_objects([{"canon": "NGC6960", "catalog": "NGC", "kind": "deep_sky"}])
    assert len(_pozycje_skrotu(bar)) == 1
    bar.set_recent_objects([])                              # pusta historia = czyste menu
    assert not _pozycje_skrotu(bar)
    # …i ŻADNA akcja nie przybyła: pula jest stała, bo `deleteLater` na QAction wywalał Qt
    # (bramka pakietu, zarzut 8 - lekarstwo gorsze od choroby, zmierzone na pełnej baterii).
    assert len(bar.btn_object.menu().actions()) == 2 + 1 + bar._RECENT_MAX
    bar.close()


def test_zmiana_motywu_PRZEZYWA_pusta_grupe(qapp):
    """Regresja złapana pełną baterią: `refresh_theme` rozpakowywał dane KAŻDEGO wiersza, więc
    placeholder (`UserRole is None`) wywracał przełączenie skórki wyjątkiem — a testy listwy
    motywu nie ruszają.

    To TRZECI konsument roli `UserRole` w tym pliku, który zakładał, że wiersz zawsze niesie
    wartość facetu (po `_on_item_clicked` i `_on_item_right_clicked`). Pin jest na KLASĘ: każde
    przejście po itemach ma przeżyć wiersz bez danych.

    Falsyfikator: zdejmij guard `dane is None` z `refresh_theme` → TypeError."""
    rail = _rail_z_obiektami(qapp)
    assert _placeholder(rail._lists["filter"]) is not None, "fikstura nie ma pustej grupy"
    rail.refresh_theme()                                   # nie może rzucić
    rail.search.setText("nic-takiego-nie-ma")
    qapp.processEvents()
    rail.refresh_theme()                                   # …także przy pustej szukajce obiektów
    rail.hide()


def test_reveal_PRZEZYWA_wiersz_stanu_pustego(qapp):
    """Zarzut 3 bramki: CZWARTA pętla po itemach (`_reveal`) rozpakowywała dane każdego wiersza.

    Docstring obiecuje „cichy no-op" dla wartości spoza listy, a od R-S3-5 był to `TypeError` —
    i to na SEAMIE dla wejść z zewnątrz (most „Pokaż klatki celu" z planera).

    Falsyfikator: zdejmij `dane is not None` z `_reveal` → TypeError."""
    rail = _rail_z_obiektami(qapp)
    assert _placeholder(rail._lists["filter"]) is not None
    rail.set_data({"object": [(1, "LMC", 3)], "filter": [], "kind": [],
                   "telescope": [], "night": []}, {}, reveal=("filter", "nie-ma-mnie"))
    rail.hide()


def test_sygnal_pozycji_menu_NIE_wciska_checked_jako_nazwy(obj_view, monkeypatch):
    """PIN NA SZWIE Qt (firsthand 0810, znalezisko 3 — skutek uboczny naprawy).

    `_on_object_name` wisi na `QAction.triggered`, a ten sygnał emituje `checked: bool`. Gdyby
    nowy parametr był POZYCYJNY, kliknięcie pozycji menu wstawiłoby `False` jako preselektowany
    kanon — cicho, bo pętla po bibliotece po prostu by go nie znalazła, a okno otwierałoby się
    z pustym combo tak samo jak przedtem. Defekt byłby więc niewidoczny do chwili, w której ktoś
    zacząłby na tym parametrze cokolwiek opierać.

    Gwiazdka w sygnaturze zamienia tę klasę pomyłki w `TypeError`; ten test pilnuje, że sam
    sygnał wchodzi bez argumentu, czyli że gwiazdka nie zepsuła drogi pozycji menu.

    Falsyfikator: zdejmij `*` z `_on_object_name` → `preselect_canon` przyjmuje `False`."""
    zapis = {}

    class _Fake:
        def __init__(self, con, *, object_raw, frame_count, selection=None, cleared_n=0,
                     preselect_canon=None, parent=None):
            zapis["preselect_canon"] = preselect_canon
            self.selected = None

        def exec(self):
            return 0

    v, con = obj_view
    monkeypatch.setattr("horreum.gui.grid.AssignObjectDialog", _Fake)
    v.refresh()
    _zaznacz(v, [1, 2])
    v._update_count()
    assert v.sel_bar.act_name.isEnabled(), "pozycja wygaszona — `trigger()` nic by nie zrobił"
    v.sel_bar.act_name.trigger()
    assert zapis["preselect_canon"] is None, "sygnał wcisnął `checked` w miejsce nazwy obiektu"


def test_skrot_ODDAJE_STER_OKNU_gdy_ma_zgasic_nagrobek(view, monkeypatch):
    """Zarzut 4 bramki: skrót miał komplet bramek technicznych, ale gubił DYSKLOZURĘ — okno mówi,
    ile nagrobków ręki zgaśnie i ile cudzych nazw nadpisze, a dwa kliknięcia robiły to po cichu.

    Kontrakt `AssignObjectDialog` stawia to zdanie na DRODZE KLIKNIĘCIA, nie w tooltipie.

    Falsyfikator: zdejmij gałąź `overwrite or user_cleared` → skrót pisze wprost i okno nie wstaje."""
    from horreum.gui import queries as q
    v = view[0] if isinstance(view, tuple) else view
    otwarte = []
    monkeypatch.setattr(v, "_on_object_name",
                        lambda *, preselect_canon=None: otwarte.append(preselect_canon))
    monkeypatch.setattr(v, "_object_gesture_ids", lambda: [1, 2])

    # 1) jest co zgasić (nagrobek) → ster do okna
    monkeypatch.setattr(q, "selection_object_state", lambda con, ids: {
        "conflict": False, "conflict_n": 0, "overwrite": 0, "expected_object_id": None,
        "by_source": {"user_cleared": 2}, "namable": 2})
    v._on_object_recent("NGC6960", "NGC", "deep_sky")
    # WYBÓR JEDZIE Z NIM (firsthand 0810, znalezisko 3): okno pyta o zgodę na zgaszenie werdyktu,
    # nie o nazwę — bez preselekcji user musiał powtórzyć w combo wybór, który przed chwilą
    # kliknął, i skrót kosztował 5 interakcji zamiast 3.
    assert otwarte == ["NGC6960"]

    # 2) jest co nadpisać (cudza nazwa ze źródła słabego) → też okno
    otwarte.clear()
    monkeypatch.setattr(q, "selection_object_state", lambda con, ids: {
        "conflict": False, "conflict_n": 0, "overwrite": 3, "expected_object_id": None,
        "by_source": {}, "namable": 3})
    v._on_object_recent("NGC6960", "NGC", "deep_sky")
    assert otwarte == ["NGC6960"]
