"""Widok „Klatki" (PLAN_gui_grid) — testy STERUJĄCE realnym oknem Qt (offscreen). Model 3 stanów +
sort + grupowanie; FilterPanel → drzewo; FramesView refresh/filtr/perspektywa. `importorskip` na poziomie
modułu (§9.4): bez PySide6 plik się POMIJA (pełny pytest bez Qt zostaje prawdziwy)."""
import json
import os
import pathlib

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from horreum import db, naming, pivot as pivot_mod, writeback
from horreum.gui import grid as grid_mod, queries, rows as rows_mod, tasks as tasks_mod

_ZRODLO_GRIDU = pathlib.Path(grid_mod.__file__).read_text(encoding='utf-8')

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


def test_belka_grupy_ZNA_STAN_ktory_zna_komorka(gcon):
    """FC-3: „Grupuj wg: Obiekt" malowało `▸ DARK (14)` białym pogrubieniem — dokładnie tak, jak
    `▸ CTB1 (901)` — choć komórki pod belką były kursywą i szare. Jeden ekran mówił o tych samych
    klatkach dwie różne rzeczy; naprawa polityki kolumny (R-S3-4) objęła komórkę i ominęła belkę.

    Populacja realna: 2364 klatki kalibracji, 79 grup, największa 2344 klatki (zmierzone 0815).

    Bramka pilnuje też GRANICY: belka grupowania po czymkolwiek innym niż obiekt stanu nie ma —
    „▸ fits (900)" nie jest o obiekcie i wyciszenie jej byłoby zdaniem o niczym."""
    from horreum.gui.grid import BASE_COLS, GridTableModel

    base = [
        {"frame_id": 1, "path": "a", "kind": "light", "_telescope": "",
         "_object": "CTB1", "_object_state": "canon"},
        {"frame_id": 2, "path": "b", "kind": "flat", "_telescope": "",
         "_object": "FlatWizard", "_object_state": "kind", "object_raw": "FlatWizard"},
    ]
    m = GridTableModel()
    m.set_data(base, pivot_mod.build_pivot([1, 2], [], []), [], group_by="_object")
    belki = {r["_group"]: m._rows.index(r) for r in m._rows if "_group" in r}
    kanon, kalibracja = m.index(belki["CTB1"], 0), m.index(belki["FlatWizard"], 0)

    assert m.data(kanon, Qt.FontRole).bold() and not m.data(kanon, Qt.FontRole).italic()
    assert m.data(kanon, Qt.ForegroundRole) is None
    assert m.data(kanon, Qt.ToolTipRole) is None

    assert m.data(kalibracja, Qt.FontRole).bold(), "belka zostaje belką"
    assert m.data(kalibracja, Qt.FontRole).italic(), "…ale mówi to samo, co komórki pod nią"
    assert m.data(kalibracja, Qt.ForegroundRole) is not None
    assert "DEFINICJI" in m.data(kalibracja, Qt.ToolTipRole), "belka niesie zdanie SWOJEGO stanu"

    m.set_data(base, pivot_mod.build_pivot([1, 2], [], []), [], group_by="kind")
    obce = [r for r in m._rows if "_group" in r]
    assert all(r["_group_state"] is None for r in obce), "grupowanie nie po obiekcie nie ma stanu"
    assert all(not m.data(m.index(m._rows.index(r), 0), Qt.FontRole).italic() for r in obce)


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


# ---- listwa: kadr po przeładowaniu (W-6 sufit z wiersza · W-7 + FH-5 wybór w kadrze) ----

def _pompuj(qapp):
    """Dwa obroty pętli, nie jeden: opóźnione komunikaty układu (nowy sufit grupy, geometria
    viewportu) wchodzą dopiero w drugim - sonda z jednym `processEvents()` mierzy fikcję. Wzorzec:
    `_pokazane` w `test_gui_mainwindow`."""
    qapp.processEvents()
    qapp.processEvents()


def _kadr_rail(qapp, counts, state=None, wys=500):
    """Listwa POKAZANA (geometria viewportu jest prawdziwa dopiero po `show()`), z pętlą gestu jak
    we FramesView: `facetsChanged` → `set_data` nowym stanem. Wołający chowa ją w `finally`."""
    from horreum.gui.facets import FacetRail
    rail = FacetRail()
    rail.resize(260, wys)
    rail.show()
    rail.facetsChanged.connect(lambda st: rail.set_data(counts, st))
    rail.set_data(counts, state or {})
    _pompuj(qapp)
    return rail


def _wiersz_listwy(rail, facet, value):
    """Wiersz listwy po wartości (`UserRole`), z pominięciem wiersza stanu pustego."""
    lw = rail._lists[facet]
    for i in range(lw.count()):
        dane = lw.item(i).data(Qt.UserRole)
        if dane is not None and dane[1] == value:
            return lw.item(i)
    raise AssertionError(f"brak wartości {value!r} w facecie {facet}")


def _w_kadrze(rail, facet, value):
    """Wiersz wartości W CAŁOŚCI w kadrze listy. Liczony w teście OSOBNO od predykatu listwy -
    bramka pytająca produkcyjnym predykatem zgodziłaby się z każdym jego błędem. Tylko pion:
    `visualItemRect` długiej nazwy ma szerokość treści, nie viewportu."""
    lw = rail._lists[facet]
    r, kadr = lw.visualItemRect(_wiersz_listwy(rail, facet, value)), lw.viewport().rect()
    return r.isValid() and r.top() >= kadr.top() and r.bottom() <= kadr.bottom()


def _widac_wiersz(rail, facet, value):
    """Wiersz wartości choćby CZĘŚCIOWO w kadrze - też liczony w teście, osobno od listwy."""
    lw = rail._lists[facet]
    r, kadr = lw.visualItemRect(_wiersz_listwy(rail, facet, value)), lw.viewport().rect()
    return r.isValid() and r.bottom() >= kadr.top() and r.top() <= kadr.bottom()


def _kadr_z_ucietym_brzegiem(lw, pelnych=7):
    """Kadr listy = `pelnych` całych wierszy + POŁOWA następnego, czyli dolny wiersz ucięty na
    brzegu - zwykły stan długiej grupy, której wysokość daje layout, a nie wielokrotność wiersza.
    Wysokość z realnego wiersza, nie stała px: układ ma powstać przy każdym foncie."""
    wiersz = lw.sizeHintForRow(0)
    lw.setFixedHeight(2 * lw.frameWidth() + pelnych * wiersz + wiersz // 2)


def test_facet_rail_krotka_grupa_miesci_CALE_wiersze_przy_kazdym_foncie(qapp):
    """W-6 (wizytacja 0810): sufit grupy krótkiej był stałą 72 px, a przy wierszu 16 px to 4,375
    wiersza - Rodzaj pokazywał połówkę `master_dark`, która czyta się jak ostatni wiersz, a nie jak
    zapowiedź dalszych. Sufit ma być wielokrotnością REALNEGO wiersza, więc bramka mierzy DWA fonty:
    stała px trafia w całe wiersze najwyżej przy jednym (tu 12 i 19 px, na pulpicie 16 px). Na
    liście stoi `✓` - pogrubiony wiersz ma mieć tę samą wysokość co reszta.

    Listwa jest WYSOKA, żeby grupy krótkie stały na suficie: bramka mierzy sufit, a nie ściskanie
    przez layout przy niskim oknie.

    Falsyfikator: przywróć w `_dopasuj_sufit` stałą 72 px → viewport 70 px przy wierszu 12 px
    (5,83 wiersza); licz sufit tylko w konstruktorze → pada drugi font (48 px przy wierszu 19 px)."""
    from PySide6.QtGui import QFont
    from horreum.gui.facets import _SHORT_ROWS
    wartosci = [(f"W{i}", f"W{i}", 9 - i) for i in range(7)]
    counts = {"object": [(1, "M31", 1)], "filter": wartosci, "kind": wartosci,
              "telescope": wartosci, "night": [("2025-01-01", "2025-01-01", 1)]}
    rail = _kadr_rail(qapp, counts, wys=900)
    try:
        bazowy = rail.font()
        wiersze = set()
        for skala in (1.0, 1.6):
            font = QFont(bazowy)
            font.setPointSizeF(bazowy.pointSizeF() * skala)
            rail.setFont(font)
            rail.set_data(counts, {"kind": {"in": [["W0", "W0"]]}})
            _pompuj(qapp)
            for facet in ("filter", "kind", "telescope"):
                lw = rail._lists[facet]
                wiersz, vp = lw.sizeHintForRow(0), lw.viewport().height()
                assert lw.height() == lw.maximumHeight(), f"{facet}: grupa nie stoi na suficie"
                assert vp % wiersz == 0, f"{facet} ×{skala}: viewport {vp} px = {vp / wiersz:.3f} wiersza"
                assert vp // wiersz == _SHORT_ROWS
                wiersze.add(wiersz)
        assert len(wiersze) == 2, f"oba fonty dały wiersz {wiersze} - bramka nie zmierzyła dwóch metryk"
    finally:
        rail.hide()


def test_facet_rail_klik_SPOZA_kadru_stawia_wybor_w_kadrze(qapp):
    """W-7 (wizytacja 0810): po kliku `Rodzaj = unknown` wiersz `✓ unknown` stał na y=80 przy
    viewporcie 70 px - niewidoczny bez scrolla, bo listwa odtwarza scroll sprzed kliku. Klik spoza
    kadru przychodzi gestem programowym (tak kliknęła wizytacja) albo Enterem szukajki (bramka
    niżej); przeładowanie wywołane gestem ma postawić klikniętą wartość w kadrze.

    Falsyfikator: zdejmij w `_dopilnuj_kadru` gałąź klikniętej wartości (i `klik` z widzianych)
    → `✓ unknown` zostaje pod kadrem."""
    rodzaje = ["light", "dark", "flat", "bias", "master_dark", "master_flat", "unknown"]
    counts = {"object": [], "filter": [], "telescope": [], "night": [],
              "kind": [(k, k, 9 - i) for i, k in enumerate(rodzaje)]}
    rail = _kadr_rail(qapp, counts)
    try:
        assert not _w_kadrze(rail, "kind", "unknown"), "wiersz w kadrze już przed klikiem - brak układu"
        rail._on_item_clicked(_wiersz_listwy(rail, "kind", "unknown"))
        _pompuj(qapp)
        assert rail.state() == {"kind": {"in": [["unknown", "unknown"]]}}
        assert _wiersz_listwy(rail, "kind", "unknown").text() == "✓ unknown"
        assert _w_kadrze(rail, "kind", "unknown"), "kliknięty wybór poza kadrem"
    finally:
        rail.hide()


def test_facet_rail_WIDZIANY_wybor_przesuniety_przeladowaniem_wraca_do_kadru(qapp):
    """W-7, człon „widziany": wybór stał w kadrze, a przeładowanie przesunęło jego wiersz. Tu nad
    wyborem przybywa 30 wierszy - tak zmienia się sibling-set Obiektu po kliku w sąsiedniej grupie.
    Scroll wraca na starą pozycję, więc `✓`, na który user patrzył, wypadał pod kadr.

    Falsyfikator: zdejmij w `_dopilnuj_kadru` człon widzianych wyborów → wiersz zostaje pod kadrem."""
    przed = [(i, f"OBJ{i:03d}", 1) for i in range(60)]
    po = [(100 + i, f"AAA{i:03d}", 1) for i in range(30)] + przed
    counts = {"object": przed, "filter": [], "kind": [], "telescope": [], "night": []}
    stan = {"object": {"in": [[30, "OBJ030"]]}}
    rail = _kadr_rail(qapp, counts, stan)
    try:
        rail._lists["object"].verticalScrollBar().setValue(28)   # user przewinął do wyboru
        _pompuj(qapp)
        assert _w_kadrze(rail, "object", 30), "wybór poza kadrem już przed przeładowaniem"
        rail.set_data(dict(counts, object=po), stan)
        _pompuj(qapp)
        assert _w_kadrze(rail, "object", 30), "widziany wybór wypadł z kadru po przeładowaniu"
    finally:
        rail.hide()


def test_facet_rail_enter_szukajki_na_trafieniu_SPOZA_kadru_odslania_je(qapp):
    """W-7, droga Enter (R-S3-6): Enter bierze PIERWSZE widoczne trafienie, a ono bywa NAD kadrem -
    fraza schowała wiersze, scroll został przy końcu listy, więc górne trafienia leżą nad
    viewportem. Enter kończy w `_on_item_clicked`, więc obowiązuje go reguła klikniętej wartości.

    Falsyfikator: zdejmij w `_dopilnuj_kadru` gałąź klikniętej wartości → `✓ B000` zostaje nad
    kadrem, choć właśnie ją wybrałeś."""
    from PySide6.QtTest import QTest
    obiekty = [(i, f"A{i:03d}", 1) for i in range(50)] + [(100 + i, f"B{i:03d}", 1) for i in range(50)]
    counts = {"object": obiekty, "filter": [], "kind": [], "telescope": [], "night": []}
    rail = _kadr_rail(qapp, counts)
    try:
        bar = rail._lists["object"].verticalScrollBar()
        bar.setValue(bar.maximum())
        rail.search.setText("B")
        _pompuj(qapp)
        assert not _w_kadrze(rail, "object", 100), "pierwsze trafienie w kadrze - brak układu"
        QTest.keyClick(rail.search, Qt.Key_Return)
        _pompuj(qapp)
        assert rail.state() == {"object": {"in": [[100, "B000"]]}}
        assert _w_kadrze(rail, "object", 100), "Enter wybrał wartość, której nie widać"
    finally:
        rail.hide()


def test_facet_rail_deliberatny_scroll_POZA_wybor_zostaje_po_przeladowaniu(qapp):
    """Granica W-7: wybór, od którego user SAM odjechał scrollem, nie był widziany ani kliknięty,
    więc przeładowanie (klik w innej grupie, refresh po geście) nie ściąga listy z powrotem - inaczej
    odbierałoby userowi listę, którą przed chwilą przewinął.

    Falsyfikator: licz w `_dopilnuj_kadru` każdy aktywny wybór jako widziany → lista wraca do `✓`
    i pozycja scrolla się zmienia."""
    counts = {"object": [(i, f"OBJ{i:03d}", 1) for i in range(60)],
              "filter": [], "kind": [], "telescope": [], "night": []}
    stan = {"object": {"in": [[5, "OBJ005"]]}}
    rail = _kadr_rail(qapp, counts, stan)
    try:
        assert _w_kadrze(rail, "object", 5)
        bar = rail._lists["object"].verticalScrollBar()
        bar.setValue(bar.maximum())                  # user odjeżdża od wyboru
        _pompuj(qapp)
        pos = bar.value()
        assert not _w_kadrze(rail, "object", 5), "wybór dalej w kadrze - brak układu"
        rail.set_data(counts, stan)                  # przeładowanie bez gestu w tej liście
        _pompuj(qapp)
        assert bar.value() == pos
        assert not _w_kadrze(rail, "object", 5)
    finally:
        rail.hide()


def test_facet_rail_klik_w_WIDOCZNA_wartosc_w_srodku_listy_nie_rusza_scrolla(qapp):
    """Granica W-7 od strony kursora (firsthand F4): klik w wartość, która stoi W CAŁOŚCI w kadrze,
    nie przewija listy przez cały cykl none → in → ex → none - user klika tę samą wartość ponownie
    i lista nie może uciec spod kursora. Wartość celowo w PIERWSZYM wierszu kadru, nie w jego
    środku: przewinięcie „na środek" zmieniłoby pozycję.

    Falsyfikator: przewijaj w `_dopilnuj_kadru` klikniętą wartość bez pytania o kadr → pozycja
    scrolla zmienia się już po pierwszym kliku."""
    counts = {"object": [(i, f"OBJ{i:03d}", 1) for i in range(60)],
              "filter": [], "kind": [], "telescope": [], "night": []}
    rail = _kadr_rail(qapp, counts)
    try:
        bar = rail._lists["object"].verticalScrollBar()
        bar.setValue(20)
        _pompuj(qapp)
        assert _w_kadrze(rail, "object", 20)
        for _ in range(3):
            rail._on_item_clicked(_wiersz_listwy(rail, "object", 20))
            _pompuj(qapp)
            assert bar.value() == 20
            assert _w_kadrze(rail, "object", 20)
        assert rail.state() == {}                    # cykl domknięty - trzy kliki, trzy przeładowania
    finally:
        rail.hide()


def test_facet_rail_klik_w_wiersz_UCIETY_na_brzegu_nie_ucieka_spod_kursora(qapp):
    """Granica W-7 na brzegu kadru: klik w wiersz UCIĘTY dolną krawędzią długiej listy nie przewija
    jej. Lista przewija się per WIERSZ (scroll 36 = wiersz 36), więc każde dociągnięcie takiego
    wiersza do kadru - na środek czy „tylko tyle, ile trzeba" - przesuwa ją o cały wiersz, a drugi
    klik cyklu ⊖ w TE SAME współrzędne trafia w sąsiada. Wiersz widoczny choćby częściowo jest
    w kadrze. Kliki idą myszą (`QTest.mouseClick`) w jeden punkt, nie w wartość.

    Falsyfikator: przywróć w `_dopilnuj_kadru` kryterium „w całości" → scroll zmienia się po
    pierwszym kliku, a pod kursorem staje inna wartość."""
    from PySide6.QtTest import QTest
    counts = {"object": [(i, f"OBJ{i:03d}", 1) for i in range(60)],
              "filter": [], "kind": [], "telescope": [], "night": []}
    rail = _kadr_rail(qapp, counts)
    try:
        lw = rail._lists["object"]
        _kadr_z_ucietym_brzegiem(lw)
        _pompuj(qapp)
        bar = lw.verticalScrollBar()
        bar.setValue(10)
        _pompuj(qapp)
        pos = bar.value()
        punkt = QPoint(10, lw.viewport().rect().bottom())     # ostatni piksel kadru = wiersz ucięty
        value = lw.itemAt(punkt).data(Qt.UserRole)[1]
        assert _widac_wiersz(rail, "object", value) and not _w_kadrze(rail, "object", value), \
            "dolny wiersz nie jest ucięty - brak układu"
        QTest.mouseClick(lw.viewport(), Qt.LeftButton, Qt.NoModifier, punkt)
        _pompuj(qapp)
        assert rail.state() == {"object": {"in": [[value, f"OBJ{value:03d}"]]}}
        assert bar.value() == pos, "klik w ucięty wiersz przewinął listę"
        assert lw.itemAt(punkt).data(Qt.UserRole)[1] == value, "pod kursorem stoi już inna wartość"
        QTest.mouseClick(lw.viewport(), Qt.LeftButton, Qt.NoModifier, punkt)   # drugi klik cyklu
        _pompuj(qapp)
        assert rail.state() == {"object": {"ex": [[value, f"OBJ{value:03d}"]]}}
        assert bar.value() == pos
    finally:
        rail.hide()


def test_facet_rail_wybor_UCIETY_na_brzegu_zostaje_przy_kliku_w_INNEJ_grupie(qapp):
    """Lista, w której nic się nie zmieniło, nie rusza się tylko dlatego, że jej aktywny wybór stoi
    ucięty na brzegu kadru. Klik w Rodzaju przeładowuje CAŁĄ listwę; Obiekt z wyborem na dolnym
    brzegu ma zostać tam, gdzie user go zostawił - wybór WIDAĆ, więc nie ma czego przywracać.

    Falsyfikator: przywróć w `_dopilnuj_kadru` kryterium „w całości" → lista Obiekt przewija się
    na środek po kliku w cudzej grupie."""
    counts = {"object": [(i, f"OBJ{i:03d}", 1) for i in range(60)],
              "kind": [("light", "light", 50), ("dark", "dark", 10)],
              "filter": [], "telescope": [], "night": []}
    stan = {"object": {"in": [[17, "OBJ017"]]}}
    rail = _kadr_rail(qapp, counts, stan)
    try:
        lw = rail._lists["object"]
        _kadr_z_ucietym_brzegiem(lw)
        _pompuj(qapp)
        bar = lw.verticalScrollBar()
        bar.setValue(10)                               # 7 całych wierszy: OBJ017 ucięty na dole
        _pompuj(qapp)
        pos = bar.value()
        assert _widac_wiersz(rail, "object", 17) and not _w_kadrze(rail, "object", 17), \
            "wybór nie stoi ucięty na brzegu - brak układu"
        rail._on_item_clicked(_wiersz_listwy(rail, "kind", "light"))
        _pompuj(qapp)
        assert rail.state() == {"object": {"in": [[17, "OBJ017"]]},
                                "kind": {"in": [["light", "light"]]}}
        assert bar.value() == pos, "lista Obiekt uciekła po kliku w innej grupie"
    finally:
        rail.hide()


def test_facet_rail_po_gescie_osi_wybor_w_PINIE_zostaje_w_kadrze(view, gcon, qapp):
    """FH-5 (firsthand 0816) na realnym geście osi. Widok zawężony do `NGC3623` mostem z planera
    (odsłonięcie ustawia scroll pod wybór), potem „Obiekt ▾ → Cofnij przypisanie" na jego klatce:
    obiekt traci klatki w sibling-secie, więc `✓` schodzi do PINU na wierszu 0, a listwa
    odtwarzała scroll z chwili odsłonięcia - zmierzone y −576, listwa pokazywała NGC281…NGC4565
    i ani śladu wyboru.

    Droga: REALNY gest (`_on_object_clear` na zaznaczeniu, jak bramki osi niżej), nie podmiana
    danych - i bez zmiany w `grid.py`, bo reguła mieszka w listwie.

    Falsyfikator: zdejmij w `_dopilnuj_kadru` człon widzianych wyborów → `✓ NGC3623` na wierszu 0
    zostaje nad kadrem."""
    kanony = sorted({f"NGC{1000 + 97 * i}" for i in range(60)} | {"NGC3623"})
    ids = _lighty_z_obiektami(gcon, kanony)
    i = kanony.index("NGC3623")
    oid, fid = 100 + i, ids[i]
    view.resize(1400, 800)
    view.show()
    try:
        _pompuj(qapp)
        view.apply_object_facet([(oid, "NGC3623")])
        _pompuj(qapp)
        rail, lw = view.facet_rail, view.facet_rail._lists["object"]
        assert lw.verticalScrollBar().value() > 0, "odsłonięcie nie przewinęło - brak układu FH-5"
        assert _w_kadrze(rail, "object", oid)
        _zaznacz(view, [fid])
        view._on_object_clear()
        _pompuj(qapp)
        assert lw.item(0).data(Qt.UserRole)[1] == oid, "wybór nie zszedł do pinu - brak układu FH-5"
        assert (lw.item(0).text(), lw.item(0).data(rows_mod.SECONDARY)) == ("✓ NGC3623", "(0)")
        assert _w_kadrze(rail, "object", oid), "✓ po geście osi poza kadrem listwy"
    finally:
        view.hide()


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


# ---------- D-V-9: adres żywej kopii + stary adres jako HISTORIA (wariant rozwojowy) ----------

def _zasiej_dwa_adresy(con):
    """Klatka z martwym adresem (wjechał pierwszy) i żywym - kształt 128 masterów z żywej bazy."""
    con.execute("INSERT INTO frame (id, sha1_data, kind, filetype, first_seen_at) "
                "VALUES (5, 'd5', 'master_light', 'xisf', ?)", (NOW,))
    con.executemany(
        "INSERT INTO location (frame_id, volume, path, present) VALUES (?,?,?,?)",
        [(5, "V", "/stare/masterLight_BIN-1.xisf", 0), (5, "V", "/nowe/Cr464_2023-05-07.xisf", 1)])
    con.commit()
    martwa, zywa = con.execute(
        "SELECT MIN(CASE WHEN present = 0 THEN id END), MIN(CASE WHEN present = 1 THEN id END) "
        "FROM location WHERE frame_id = 5").fetchone()
    assert martwa < zywa, "fikstura nie odtwarza pułapki: martwa kopia MUSI mieć niższe id"


def test_komorka_sciezki_pokazuje_zywa_kopie(view, gcon):
    """D-V-9 na EKRANIE: komórka „Ścieżka" niesie nazwę pliku, który istnieje. Do naprawy wiersz
    pokazywał martwy adres i nie mówił o tym niczym - znacznik zniknięcia wymaga `n_present == 0`."""
    _zasiej_dwa_adresy(gcon)
    view.refresh()
    r = next(i for i, row in enumerate(view.model._rows) if row.get("frame_id") == 5)
    assert view.model.data(view.model.index(r, 0), Qt.DisplayRole) == "Cr464_2023-05-07.xisf"


def test_tooltip_niesie_wczesniejszy_adres(view, gcon):
    """Wariant rozwojowy: stary adres przestaje być śmieciem i staje się widoczną historią
    przeprowadzki. Człon DOKLEJA SIĘ do bieżącej ścieżki, nie zastępuje jej."""
    _zasiej_dwa_adresy(gcon)
    view.refresh()
    tip = _path_tip(view, 5)
    assert "/nowe/Cr464_2023-05-07.xisf" in tip                  # bieżący adres dalej na górze
    assert "wcześniejszy adres" in tip and "/stare/masterLight_BIN-1.xisf" in tip


def test_tooltip_znikietej_nie_mowi_o_wczesniejszym_adresie(view, gcon):
    """Warunek SENSU, nie ostrożność: przy klatce znikniętej pokazany adres SAM jest tym martwym,
    więc „miała wcześniej adres X" wskazywałoby to, co user właśnie czyta w komórce."""
    view.refresh()
    tip = _path_tip(view, 4)                                     # f4: jedyna kopia present=0
    assert "zniknięta" in tip and "wcześniejszy adres" not in tip


def test_tooltip_dwa_martwe_adresy_podaje_liczbe_i_pierwszy(view, gcon):
    """Gałąź MNOGA `_former_tip` - jedyna nieprzetestowana ścieżka nowej funkcji (bramka pakietu Z4).
    Populacja żywej bazy: 0 klatek z dwoma martwymi adresami, więc broni jej wyłącznie ten test.
    Tooltip podaje LICZBĘ i pierwszy adres zamiast sklejać listę: ma się przeczytać jednym
    spojrzeniem, a pełny wykaz kopii ma własną powierzchnię."""
    _zasiej_dwa_adresy(gcon)
    gcon.execute("INSERT INTO location (frame_id, volume, path, present) "
                 "VALUES (5, 'V', '/jeszcze-starsze/master.xisf', 0)")
    gcon.commit()
    view.refresh()
    tip = _path_tip(view, 5)
    assert "wcześniejsze adresy (2)" in tip
    assert "/stare/masterLight_BIN-1.xisf" in tip           # PIERWSZY martwy, nie ostatni dopisany
    assert "/nowe/Cr464_2023-05-07.xisf" in tip             # bieżący adres dalej na górze


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
    """Wiz F5 #8: pusty grid mówi DWIE różne rzeczy. Na bazie z klatkami komunikat wskazuje
    zawężenie, które nie wpuściło klatek (od FH-4 tym samym gestem co recepta paska); na PUSTEJ
    bazie takie wskazanie wysyłałoby usera w ślepy zaułek (nie ma czego filtrować) - tam
    komunikat kieruje po dostawę."""
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


def test_komorka_obiektu_MALUJE_zeznanie_inaczej_niz_kanon(gcon):
    """R-S3-4 NA POWIERZCHNI — sama polityka pięciu stanów ma dom w `test_gui_queries` (Qt-wolny).
    Tu dowodzimy, że model REALNIE ją maluje: kanon bez ról, zeznanie z kursywą, szarością
    i własnym tooltipem.

    Falsyfikator: zdejmij gałąź `key == "_object"` z `_base_cell` → wiersz cofnięty renderuje się
    identycznie jak nazwany, czyli wraca dokładnie ten defekt (jeden ekran, dwa sprzeczne zdania
    o tych samych klatkach: kolumna pokazuje `NGC7023`, facet Obiekt obok jest pusty)."""
    from horreum.gui.grid import GridTableModel, BASE_COLS

    m = GridTableModel()
    m.set_data([
        {"frame_id": 1, "path": "a", "kind": "light", "_telescope": "",
         "_object": "NGC 7023", "_object_state": "canon"},
        {"frame_id": 2, "path": "b", "kind": "light", "_telescope": "",
         "_object": "↺ NGC7023", "_object_state": "cleared"},
    ], pivot_mod.build_pivot([1, 2], [], []), [])
    kol = [k for _, k in BASE_COLS].index("_object")
    kanon, cofniete = m.index(0, kol), m.index(1, kol)

    assert m.data(kanon, Qt.DisplayRole) == "NGC 7023"
    assert m.data(kanon, Qt.FontRole) is None and m.data(kanon, Qt.ForegroundRole) is None
    assert m.data(kanon, Qt.ToolTipRole) is None, "kanon mówi sam za siebie — tooltip byłby szumem"

    assert m.data(cofniete, Qt.DisplayRole) == "↺ NGC7023"
    assert m.data(cofniete, Qt.FontRole).italic()
    assert m.data(cofniete, Qt.ForegroundRole) is not None
    tip = m.data(cofniete, Qt.ToolTipRole)
    assert "COFNIĘTE" in tip and "Przywróć" in tip, "tooltip niesie RECEPTĘ, nie samą diagnozę"


def test_komorka_obiektu_KAZDY_stan_ma_WLASNY_tooltip(gcon):
    """Cztery niekanoniczne stany, cztery różne zdania — bo każdy ma inną drogę naprawy: nagrobek
    zdejmuje się drugim gestem ręki, nazwę z nagłówka poprawia się w PLIKU, a kalibracji nie
    poprawia się wcale (obiektu nie ma z definicji). Wspólny tooltip byłby prawdziwy i bezużyteczny.

    Falsyfikator: wskaż dwa stany na ten sam klucz w `_OBJECT_STATE_TIPS` → zbiór się skurczy."""
    from horreum.gui.grid import BASE_COLS, GridTableModel, _OBJECT_STATE_TIPS

    stany = list(_OBJECT_STATE_TIPS)
    m = GridTableModel()
    m.set_data([{"frame_id": i, "path": "p", "kind": "light", "_telescope": "",
                 "_object": "x", "_object_state": s} for i, s in enumerate(stany)],
               pivot_mod.build_pivot(list(range(len(stany))), [], []), [])
    kol = [k for _, k in BASE_COLS].index("_object")
    tips = {m.data(m.index(i, kol), Qt.ToolTipRole) for i in range(len(stany))}
    assert len(tips) == len(stany), f"stany dzielą tooltip: {tips}"
    assert all(t and not t.startswith("grid.cell.") for t in tips), "surowy klucz na ekranie"


def test_ZADNA_kontrolka_nie_pokazuje_surowego_klucza_i18n(view):
    """BRAMKA KLASY: napis widoczny w oknie nie ma prawa BYĆ kluczem katalogu.

    Znalezione sondą na żywym archiwum, nie recenzją: listwa „Grupuj wg" pokazywała
    `object.col.name`, `frame.col.camera`, `grid.col.dt_delta` — SZEŚĆ z siedmiu pozycji było
    kluczem wewnętrznym, bo `BASE_COLS` niesie klucze, a rozwiązywał je wyłącznie `headerData`
    tabeli. Istniejące bramki i18n tego nie łapały i nie mogły: pilnują, żeby klucz ISTNIAŁ
    w katalogu (`test_klucze_call_site_podzbior_katalogu`) i żeby stan MIAŁ klucz — żadna nie pyta,
    czy napis PRZESZEDŁ przez `t()`. Ta pyta o to od strony ekranu.

    Zbiór kluczy bierzemy z katalogu, więc bramka rośnie razem z nim, a fałszywy trafiony jest
    strukturalnie niemożliwy: klucze mają kropki, etykiety nie.

    Falsyfikator: wróć do `addItem(label, key)` bez `t()` → padają wszystkie pozycje listwy."""
    from PySide6.QtGui import QAction
    from PySide6.QtWidgets import QAbstractButton, QComboBox, QLabel

    from horreum.gui.i18n_catalog import CATALOG

    napisy = set()
    for w in view.findChildren(QLabel) + view.findChildren(QAbstractButton):
        napisy.add(w.text())
    for c in view.findChildren(QComboBox):
        napisy |= {c.itemText(i) for i in range(c.count())}
    for a in view.findChildren(QAction):
        napisy.add(a.text())
    napisy |= {view.model.headerData(c, Qt.Horizontal, Qt.DisplayRole)
               for c in range(view.model.columnCount())}

    surowe = sorted(napisy & set(CATALOG))
    assert not surowe, f"kontrolka pokazuje KLUCZ zamiast napisu: {surowe}"
    assert "Obiekt" in napisy, "bramka byłaby ślepa, gdyby nic nie zebrała"

    # DRUGA POŁOWA KLASY (bramka pakietu 0815, zarzut zgodny u dwóch soczewek): powyższa pętla widzi
    # wyłącznie klucz, który W KATALOGU JEST. Klucz z literówką renderuje się surowo przez fallback
    # `i18n.t` i przechodziłby, a kolektor literałów też go nie widzi, bo `BASE_COLS` idzie do `t()`
    # ZMIENNĄ. Parytet źródła z katalogiem zamyka tę połowę - wzorzec: bramka `PRESETS`/`_PRESET_LABELS`.
    from horreum.gui.grid import BASE_COLS
    obce = [k for k, _ in BASE_COLS if k not in CATALOG]
    assert not obce, f"nagłówek kolumny spoza katalogu i18n (renderuje się surowo): {obce}"


def test_belka_grupy_NIE_cytuje_wiersza_ktory_nie_reprezentuje_kubelka(gcon):
    """BRAMKA PAKIETU 0815, zarzut zgodny u DWÓCH soczewek (obcy silnik + recenzent z dostępem
    do repo). Kubełek zbiera się po TEKŚCIE komórki, a tekst nagrobka jest ten sam niezależnie od
    tego, czy klatka niesie zeznanie nagłówka i czy baza pamięta zdjęty obiekt — belka cytująca
    `bucket[0]` orzekała więc o całej grupie to, co jest prawdą o JEDNEJ klatce.

    Populacja nie jest teoretyczna: 845 klatek nieba nie ma `object_raw`, więc pierwsze masowe
    cofnięcie obejmujące klatki z nagłówkiem i bez wytwarza kubełek mieszany. Gorzej: `bucket[0]`
    zależy od bieżącego SORTU, więc zdanie belki zmieniałoby się po kliknięciu w nagłówek kolumny.

    Trzy tryby, po jednym na prawdę kubełka. Falsyfikator: wróć do `_object_tip(row["_group_row"])`
    → trzeci przypadek zacznie twierdzić „baza go pamięta" nad wierszem, który nie ma czego
    przywrócić."""
    from horreum.gui.grid import GridTableModel

    wspolne = {"path": "p", "kind": "light", "_telescope": "", "_object": "↺ NGC2903",
               "_object_state": "cleared", "object_source": "user_cleared"}
    z_pamiecia = dict(wspolne, object_cleared_canon="NGC2903")

    def belka(rows):
        m = GridTableModel()
        m.set_data(rows, pivot_mod.build_pivot([r["frame_id"] for r in rows], [], []), [],
                   group_by="_object")
        i = next(i for i, r in enumerate(m._rows) if "_group" in r)
        return m.data(m.index(i, 0), Qt.ToolTipRole), m.data(m.index(i, 0), Qt.FontRole)

    jednorodny, _ = belka([dict(z_pamiecia, frame_id=1, object_raw=None),
                           dict(z_pamiecia, frame_id=2, object_raw=None)])
    assert "ZDJĘŁA" in jednorodny, "kubełek jednogłosy dostaje zdanie dokładne"

    rozne_zeznania, _ = belka([dict(z_pamiecia, frame_id=1, object_raw="ngc2903x"),
                               dict(z_pamiecia, frame_id=2, object_raw=None)])
    assert "ZDJĘŁA" in rozne_zeznania, "pamięć mają wszystkie — o niej wolno mówić"
    assert "ngc2903x" not in rozne_zeznania, \
        "zeznanie JEDNEJ klatki nie ma prawa stać się zdaniem o całej grupie"

    mieszana_pamiec, font = belka([dict(z_pamiecia, frame_id=1, object_raw="ngc2903x"),
                                   dict(wspolne, frame_id=2, object_cleared_canon=None,
                                        object_raw="NGC2903")])
    assert mieszana_pamiec is None, \
        "przy mieszanej pamięci OBA zdania są fałszem o połowie wierszy — belka milczy"
    assert font.italic(), "…ale stan zostaje: wiersze są nagrobkami i belka ma to pokazywać"


def test_nagrobek_z_pamiecia_i_BEZ_niej_mowia_ROZNE_zdania(gcon):
    """FC-1: po tym, jak komórka zaczęła pokazywać obiekt ZDJĘTY RĘKĄ, jedno wspólne zdanie stałoby
    się fałszem w połowie przypadków. Nagrobek BEZ pamięci (baza-dawca sprzed migracji 0017 —
    wpuszczana świadomie, `0017:29`) pokazuje nazwę z NAGŁÓWKA, więc zdanie „to zdjęła ręka" byłoby
    o niej nieprawdą, a gest „Przywróć" nie ma tam czego odtworzyć i mówi o tym wprost.

    Trzeci wariant niesie zeznanie nagłówka, którego komórka już nie pokazuje — bo to ono jest drogą
    do naprawy TRWAŁEJ (karta `OBJECT` w pliku), a nie ginie tylko dlatego, że zeszło z ekranu.

    Falsyfikator: podepnij jeden tooltip pod wszystkie trzy → zbiór zdań się skurczy."""
    from horreum.gui.grid import BASE_COLS, GridTableModel

    wspolne = {"path": "p", "kind": "light", "_telescope": "", "_object": "↺ x",
               "_object_state": "cleared"}
    m = GridTableModel()
    m.set_data([
        {"frame_id": 1, "object_cleared_canon": "NGC 7023", "object_raw": None, **wspolne},
        {"frame_id": 2, "object_cleared_canon": "NGC 7023", "object_raw": "ngc7023x", **wspolne},
        {"frame_id": 3, "object_cleared_canon": None, "object_raw": "ngc7023x", **wspolne},
    ], pivot_mod.build_pivot([1, 2, 3], [], []), [])
    kol = [k for _, k in BASE_COLS].index("_object")
    z_pamiecia, z_zeznaniem, bez_pamieci = [m.data(m.index(i, kol), Qt.ToolTipRole) for i in range(3)]

    assert len({z_pamiecia, z_zeznaniem, bez_pamieci}) == 3, "trzy różne prawdy, trzy zdania"
    assert "ZDJĘŁA" in z_pamiecia and "Przywróć" in z_pamiecia
    assert "ngc7023x" in z_zeznaniem, "zeznanie nagłówka schodzi do tooltipa, nie znika"
    assert "ZDJĘŁA" not in bez_pamieci, "bez pamięci nie wolno twierdzić, że to werdykt ręki"
    assert "nie ma tu czego odtworzyć" in bez_pamieci
    assert all(not t.startswith("grid.cell.") for t in (z_pamiecia, z_zeznaniem, bez_pamieci))


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


def test_zdanie_po_odniesieniu_MOWI_ILE_KLATEK_CZEKALO_na_ten_zegar(view, gcon):
    """G2-3d. Zakres offsetu (`UTC_OFFSET_MAX_MIN`) jest bramką na NONSENS, nie na pomyłkę:
    wskazanie o dobę obok mieści się w zegarach świata i przechodzi, a jedynym śladem był potem
    powód `no_candidates` na innym ekranie, bez słowa o przyczynie. Gest zostawiał więc człowieka
    z pytaniem, na które panel przed chwilą policzył odpowiedź.

    MATERIAŁ REALNY, NIE ATRAPA (bramka pakietu, zarzut blokujący). Pierwsza wersja tej bramki
    porównywała komunikat z wynikiem tej samej funkcji i podmieniała ją `lambda: 7` - była zielona
    także wtedy, gdy licznik ZAWSZE zwracał zero, czyli nie odróżniała działającego mechanizmu od
    martwego. Trzy klatki RAW bez odniesienia dają liczbę znaną CO DO SZTUKI i niezerową.

    ⚠ LICZBA JEST CZYTANA PRZED ZAPISEM i to jest cały mechanizm: zapis offsetu czyni powód
    zwietrzałym (`queries.lineage_reason_stale`), więc odświeżenie po nim nie liczy już propozycji.
    Bramka pilnuje tego pomiarem, nie zaufaniem - stąd druga tura na tym samym stosie.

    Falsyfikator: przenieś `czekalo = …` pod `set_integration_offset` → pierwsza asercja spada
    z „3" na „0", czyli dokładnie tam, gdzie ten człon był martwy w chwili narodzin."""
    _seed_stos_z_kandydatami(gcon, reason="offset_unknown", filetype="raw")
    assert _zaznacz_frame(view, 10)
    view._toggle_panel("lineage")
    assert view.lineage_bar.klatki_bez_odniesienia() == 3, "fikstura nie dała materiału bez zegara"
    komunikaty = []
    view.status_message.connect(komunikaty.append)

    view.lineage_bar.offset_asked.emit(60)
    assert "klatek czekało na zegar: 3" in komunikaty[-1], komunikaty[-1]

    # …a DRUGI gest na tym samym stosie mówi zero i to też jest prawda: zegar jest już wskazany,
    # więc żadna klatka na niego nie czeka. Ta para asercji odróżnia licznik żywy od zamrożonego.
    view.lineage_bar.offset_asked.emit(120)
    assert "klatek czekało na zegar: 0" in komunikaty[-1], komunikaty[-1]


def test_licznik_materialu_NIE_PRZEZYWA_wyjscia_z_trybu_propozycji(view, gcon):
    """GRANICA poprzedniej bramki - i ta sama klasa co BP-4, tylko na drugim stanie. Panel trzymał
    `_nights` zapalane w `_set_candidates` i niegasnące NIGDZIE, a `_raw_bez_odniesienia` nie było
    zerowane przy wejściu w oś kalibracji: przy następnym obrazie licznik mówiłby o materiale
    POPRZEDNIEGO. Dopóki liczby nikt nie czytał, było to poprawne przez przypadek; gest odniesienia
    właśnie zrobił z niej treść komunikatu.

    Falsyfikator: zdejmij zerowanie z `set_calibration` → druga asercja czerwienieje."""
    _seed_stos_z_kandydatami(gcon, reason="offset_unknown", filetype="raw")
    assert _zaznacz_frame(view, 10)
    view._toggle_panel("lineage")
    assert view.lineage_bar.klatki_bez_odniesienia() == 3

    view.lineage_bar.set_lineage(None, [], hint="cokolwiek")
    assert view.lineage_bar.klatki_bez_odniesienia() == 0, "materiał przeżył wyjście z trybu"

    view.lineage_bar._raw_bez_odniesienia = 5          # …i ta sama granica na osi kalibracji
    view.lineage_bar.set_calibration([])
    assert view.lineage_bar.klatki_bez_odniesienia() == 0, "materiał przeżył wejście w kalibrację"


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


def test_pasek_ma_JEDNA_kontrolke_osi_z_trzema_pozycjami(obj_view):
    """§4/14c-j: pasek zyskuje JEDNĄ kontrolkę, nie osobne przyciski — siódmy i ósmy przewróciłyby
    go do drugiego rzędu. Etykiety z KLUCZA i18n, nie literałem.

    TRZECIA POZYCJA (R-S2b-3) jest WIDOCZNA ZAWSZE, także gdy nie ma czego przywracać — i to jest
    pin na tę decyzję, nie skutek uboczny. Ukrycie jej do czasu, aż pojawi się nagrobek, znaczyłoby,
    że o odwracalności gestu user dowiaduje się dopiero PO pomyłce, czyli w jedynym momencie,
    w którym ta wiedza jest już spóźniona."""
    v, _ = obj_view
    assert v.sel_bar.btn_object.menu() is not None
    from horreum.gui import i18n
    # WIDOCZNE pozycje: pula skrótu „ostatnio użyte" (R-S2b-12) żyje w tym samym menu, ale jest
    # ukryta, dopóki dziennik nie ma czego pokazać — stała pula zamiast dokładania akcji, bo
    # `deleteLater` na QAction wywalał Qt (bramka pakietu, zarzut 8).
    assert [a.text() for a in v.sel_bar.btn_object.menu().actions() if a.isVisible()] == [
        i18n.t("grid.sel.object_name"), i18n.t("grid.sel.object_clear"),
        i18n.t("grid.sel.object_restore")]


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


def test_zaznaczenie_PRZEZYWA_gest_osi(obj_view):
    """R-S2b-3, człon pierwszy. `refresh()` przebudowuje model, więc zaznaczenie 120 klatek szło do
    zera — a razem z nim JEDYNY tani cel gestu naprawczego. Zmierzone przez wizytację: odtworzenie
    stanu sprzed pomyłki kosztowało 6-8 interakcji plus pamięć człowieka o tym, co tam stało.

    Odkładanie idzie PO `frame_id`, nie po numerze wiersza — gest zmienia klucz sortu tej kolumny,
    więc numer po odświeżeniu wskazuje inną klatkę.

    Falsyfikator: zdejmij `_przywroc_zaznaczenie` z `_po_gescie_osi` → zbiór po geście jest pusty."""
    v, con = obj_view
    v.refresh()
    _zaznacz(v, [1, 2])
    assert {r["frame_id"] for r in v._selected_data_rows()} == {1, 2}
    v._on_object_clear()
    assert {r["frame_id"] for r in v._selected_data_rows()} == {1, 2}


def test_zaznaczenie_odklada_sie_JEDNYM_wywolaniem_i_bez_naglowka_grupy(obj_view):
    """DWA szwy naraz, bo oba są niewidoczne w teście, który pyta tylko o zbiór id.

    JEDNO `select()`: każde wywołanie emituje `selectionChanged`, a ten ciągnie `_update_count`
    → read-model osi (31 ms przy 16 648 klatkach). Pętla po zakresach wracałaby do kwadratu, który
    zdjęło P-K (2 071 ms → 2 ms).

    BEZ NAGŁÓWKA GRUPY: zmierzone falsyfikatorem na gołym Qt — `select()` na zakresie obejmującym
    wiersz NIESELEKTOWALNY wciąga go do `sm.selection()` (`selectedRows()` go odsiewa, ZAKRESY nie),
    a `_selected_data_rows` czyta właśnie zakresy. Bez łamania zakresów po geście podświetlałby się
    nagłówek grupy — wiersz, którego gest nie tknął.

    Falsyfikator drugiego członu: zdejmij warunek ciągłości → marker grupy wpada między klatki
    i liczba wierszy-nie-klatek w zaznaczeniu rośnie."""
    v, con = obj_view
    v.combo_group.setCurrentIndex(v.combo_group.findData("kind"))   # grupowanie ⇒ markery w liście
    v.refresh()
    _zaznacz(v, [1, 2, 3])
    ile = []
    v.table.selectionModel().selectionChanged.connect(lambda *_: ile.append(1))
    v._on_object_clear()

    assert len(ile) == 1, f"zaznaczenie odłożone {len(ile)} wywołaniami zamiast jednym"
    numery = set()
    for zakres in v.table.selectionModel().selection():
        numery.update(range(zakres.top(), zakres.bottom() + 1))
    markery = [i for i in numery if "_group" in v.model._rows[i]]
    assert not markery, f"zaznaczenie objęło nagłówki grup: {markery}"


def test_samo_odswiezenie_NIE_odklada_zaznaczenia(obj_view):
    """GRANICA CZŁONU PIERWSZEGO. Zaznaczenie przeżywa GEST OSI, a nie każdy `refresh()`: zmiana
    facetu, perspektywy i filtra to gesty, po których zaznaczenie ginąć POWINNO — user zmienił
    ZBIÓR, a nie stan tych klatek. Bez tej granicy zaznaczenie wracałoby na wierzch cudzej zmiany.

    Falsyfikator: przenieś `_przywroc_zaznaczenie` z `_po_gescie_osi` do `_refresh` → ten test
    czerwienieje, bo zaznaczenie wróci po zmianie, która go nie dotyczyła."""
    v, _ = obj_view
    v.refresh()
    _zaznacz(v, [1, 2])
    assert len(v._selected_data_rows()) == 2
    v.refresh()
    assert not v._selected_data_rows()


def test_zdanie_po_cofnieciu_MOWI_co_zdjelo(obj_view):
    """Cofnięcie kończyło się na „Cofnięto przypisanie na N z M klatek", a bliźniacze zdanie nadania
    kończy się `: NGC 7023`. Człon idzie OSOBNYM kluczem, nie placeholderem w zdaniu bazowym —
    to zdanie ma dwóch wołających o różnych kwargach.

    Falsyfikator: zdejmij człon `object_canons` → asercja o kanonie czerwienieje, a zdanie wraca
    do stanu, w którym user wie ILE, ale nie wie CO."""
    v, con = obj_view
    v.refresh()
    _zaznacz(v, [1, 2])
    msgs = []
    v.status_message.connect(msgs.append)
    v._on_object_clear()
    assert ": NGC6960" in msgs[-1], msgs[-1]

    # …a gest, który NICZEGO nie zdjął, nie dokleja członu o obiekcie, którego nie tknął.
    # Pytamy o KANON, nie o dwukropek: rozbicie pominięć („nie było czego cofać: 2") ma własny.
    msgs.clear()
    v._on_object_clear()
    assert "NGC6960" not in msgs[-1] and "nie było czego cofać: 2" in msgs[-1]


def _lighty_z_obiektami(con, kanony, start_id=11):
    """Po jednym lighcie na kanon, nadanym RĘKĄ - kolejność klatek celowo inna niż alfabetyczna."""
    for i, canon in enumerate(kanony):
        oid, fid = 100 + i, start_id + i
        con.execute("INSERT INTO object(id, canon, catalog, kind) "
                    "VALUES (?,?,'NGC','deep_sky')", (oid, canon))
        con.execute("INSERT INTO frame(id, kind, filetype, sha1_data, first_seen_at, "
                    "object_id, object_source) VALUES (?, 'light', 'raw', ?, ?, ?, 'user')",
                    (fid, f"sha-{fid}", NOW, oid))
        con.execute("INSERT INTO header(frame_id, raw_json) VALUES (?, '{}')", (fid,))
    con.commit()
    return [start_id + i for i in range(len(kanony))]


def test_para_gestow_CYTUJE_te_same_kanony_w_TYM_SAMYM_porzadku(obj_view):
    """FC-7. Cofnięcie i przywrócenie mówiły o TYM SAMYM zbiorze obiektów, a pokazywały różne
    trójki: klinga cofnięcia zbiera kanony w kolejności KLATEK, `queries.restore_targets` sortuje
    `ORDER BY o.canon`. Przy siedmiu obiektach dawało to „NGC6960, NGC5194, NGC3623 (+4)" kontra
    „IC434, LMC, Moon (+4)" - dwa zdania o jednej sprawie, nie do zestawienia wzrokiem.

    Porządek jest własnością ZDANIA, więc rozstrzyga go `_lista_kanonow`, nie żadna z dwóch kling.

    Falsyfikator: zamień `sorted(canons)` na `list(canons)` → zdanie cofnięcia wraca do porządku
    klatek („NGC7000, NGC1499, NGC6888") i przestaje się zgadzać z przywróceniem."""
    v, con = obj_view
    ids = _lighty_z_obiektami(con, ["NGC7000", "NGC1499", "NGC6888", "NGC2237"])
    v.refresh()
    msgs = []
    v.status_message.connect(msgs.append)

    _zaznacz(v, ids)
    v._on_object_clear()
    po_cofnieciu = msgs[-1]
    _zaznacz(v, ids)
    v._on_object_restore()
    po_przywroceniu = msgs[-1]

    trojka = "NGC1499, NGC2237, NGC6888 (+1)"      # alfabetycznie, nie w kolejności klatek
    assert trojka in po_cofnieciu, po_cofnieciu
    assert trojka in po_przywroceniu, po_przywroceniu


def _sluchaj_paska(v):
    """Podłącz się pod OBA kanały paska stanu (FH-2) — zwraca `(raporty, recepty)`.

    Raport („co się stało") i recepta („co możesz teraz zrobić") jadą osobno, bo mają osobne
    nośniki: raport idzie w `showMessage`, recepta na własny widżet stały. Bramka czytająca sam
    `status_message` byłaby po tej zmianie ślepa dokładnie na ten człon, o który pyta."""
    raporty, recepty = [], []
    v.status_message.connect(raporty.append)
    v.status_recipe.connect(recepty.append)
    return raporty, recepty


def test_zdanie_po_cofnieciu_PODAJE_droge_powrotu(obj_view):
    """FC-9. Odwracalność gestu jest w aplikacji od R-S2b-3, ale w chwili, w której się przydaje,
    była niewidoczna: licznik „do przywrócenia: 46" siedzi w tooltipie kontrolki, a pozycja menu
    za kliknięciem. Recepta idzie więc do zdania - i cytuje ETYKIETY z katalogu i18n, żeby zmiana
    napisu nie zostawiła w komunikacie wskazania, którego na ekranie nie ma.

    Gest, który NICZEGO nie zdjął, recepty nie dostaje: mówiłaby, jak cofnąć coś, co się nie stało.

    OD FH-2 RECEPTA NIE STOI JUŻ W RAPORCIE i to jest druga połowa tej bramki: człon dopisany na
    końcu zdania był ucinany przez `QStatusBar` bez wielokropka (zmierzone 252 znaki na 1459 px),
    więc test pyta osobno o to, że recepta JEST na swoim nośniku, i o to, że raportu już nie
    obciąża.

    Falsyfikator: zdejmij człon `object_clear_undo` z `_po_gescie_osi` → pierwsza asercja
    czerwienieje."""
    from horreum.gui import i18n
    v, con = obj_view
    v.refresh()
    _zaznacz(v, [1, 2])
    raporty, recepty = _sluchaj_paska(v)

    v._on_object_clear()
    assert i18n.t("grid.sel.object_restore") in recepty[-1], recepty[-1]
    assert i18n.t("grid.sel.object") in recepty[-1]
    assert i18n.t("grid.sel.object_restore") not in raporty[-1], raporty[-1]
    # Cel ZOSTAŁ na ekranie (brak zawężenia), więc gest jest wykonalny OD RAZU - i zdanie nie
    # każe czekać na inny gest. Wariant „potem" ma własną bramkę niżej.
    assert "potem" not in recepty[-1], recepty[-1]

    recepty.clear()
    v._on_object_clear()                       # drugi raz: nie ma czego cofać ⇒ nie ma czego cofać wstecz
    assert recepty[-1] == "", recepty[-1]      # …a pusta recepta GASI tę z poprzedniego gestu


def test_gest_MOWI_ze_wypchnal_wlasny_cel_z_widoku_I_JAK_go_odzyskac(obj_view):
    """FC-2. Cofnięcie przy aktywnym facecie „Obiekt" zostawia widok pusty - `facet_objects`
    JOIN-uje po `f.object_id`, a nagrobek z niego wypada (zmierzone na kopii żywej bazy:
    43 → 0 klatek). Cel gestu wychodzi z widoku dokładnie w chwili, w której człowiek patrzy,
    czy gest się udał.

    RECEPTA JEST TU WYKONYWANA, NIE TYLKO CYTOWANA (bramka pakietu, soczewka obca): test klika
    to, co zdanie każe kliknąć, i sprawdza, że klatki wracają. Bramka pytająca wyłącznie o TREŚĆ
    komunikatu przeszłaby także dla recepty, która nic nie odsłania - czyli dla dokładnie tej wady,
    którą ta paczka zamyka.

    Falsyfikator: zdejmij człon `out_of_view` z `_czlon_poza_widokiem` → zdanie znów potwierdza
    zapis na klatkach, których na ekranie nie ma, i milczy o tym, gdzie się podziały."""
    from horreum.gui import i18n
    v, con = obj_view
    v.apply_object_facet([(5, "NGC6960")])         # zawężenie do obiektu, który zaraz zdejmiemy
    _zaznacz(v, [1, 2])
    raporty, recepty = _sluchaj_paska(v)
    v._on_object_clear()

    widoczne = {r["frame_id"] for r in v.model._rows if isinstance(r, dict) and "frame_id" in r}
    assert not ({1, 2} & widoczne), "facet nie wypchnął nagrobków - test nie odtwarza defektu"
    # POMIAR ZOSTAJE W RAPORCIE, INSTRUKCJA IDZIE NA SWÓJ NOŚNIK (FH-2) - „poza widokiem: 2" mówi,
    # co się stało, a „odsłoni je …" mówi, co z tym zrobić.
    assert "poza widokiem: 2" in raporty[-1], raporty[-1]
    assert i18n.t("grid.sel.clear_set") in recepty[-1], recepty[-1]
    # …i to jest recepta WĘŻSZA, nie perspektywa: trimu tu nie ma, więc zbiór usera ma zostać.
    assert i18n.t("perspective.review") not in recepty[-1], recepty[-1]
    # Droga powrotu ustawiona w kolejności, w której da się ją WYKONAĆ: kontrolka „Obiekt" jest
    # w tej chwili wygaszona (zaznaczenie puste), więc zdanie mówi „potem", nie „teraz".
    assert "potem" in recepty[-1], recepty[-1]
    assert not v.sel_bar.btn_object.isEnabled(), "kontrolka żywa - bramka nie odtwarza sytuacji"

    v._on_clear_selection()                        # …wykonaj receptę
    widoczne = {r["frame_id"] for r in v.model._rows if isinstance(r, dict) and "frame_id" in r}
    assert {1, 2} <= widoczne, "recepta wykonana, a klatki się nie odsłoniły"
    # …i cel gestu WRACA W ZAZNACZENIU, więc drugi krok recepty da się wykonać. Bez tego
    # odsłonięcie jest połową drogi: firsthand zmierzył widok 16 901 wierszy z zaznaczeniem 0,
    # w którym 43 klatki gestu były nie do wyłuskania, a kontrolka „Obiekt" stała wygaszona.
    assert {r["frame_id"] for r in v._selected_data_rows()} == {1, 2}, "cel gestu zgubiony"
    assert v.sel_bar.btn_object.isEnabled(), "druga połowa recepty dalej niewykonalna"


def test_cel_gestu_wraca_TYLKO_RAZ_a_nie_przy_kazdym_odswiezeniu(obj_view):
    """GRANICA poprzedniej bramki. Zaznaczenie przeżywa GEST i gest odsłaniający po nim - a nie
    każdy późniejszy `refresh()`: zmiana kolumn, sortu czy filtra to zdarzenia, po których
    zaznaczenie ginąć POWINNO, bo user zmienił ZBIÓR, a nie stan tych klatek (R-S2b-3).

    Falsyfikator: zdejmij konsumpcję `_cel_gestu` w `refresh()` (zostaw samo odczytanie)
    → zaznaczenie wraca po każdym odświeżeniu i ta bramka czerwienieje."""
    v, con = obj_view
    v.apply_object_facet([(5, "NGC6960")])
    _zaznacz(v, [1, 2])
    v._on_object_clear()
    v._on_clear_selection()
    assert len(v._selected_data_rows()) == 2      # …pierwszy refresh po geście oddaje cel

    v.table.selectionModel().clearSelection()
    v.refresh()                                    # …a drugi już nie ma czego oddawać
    assert not v._selected_data_rows(), "zaznaczenie wraca po odświeżeniu, które go nie dotyczy"


def test_czlon_kanonow_NAZYWA_swoj_przedmiot_a_nie_przykleja_sie_do_sasiada(obj_view):
    """Człon kanonów stoi na końcu zdania, za rozbiciem pominięć, więc goły dwukropek przyklejał
    się do CUDZEJ liczby: „· z nagłówka/regionu: 482: IC434, LMC, Moon" czyta się jako nazwy tych
    482 pominiętych, a nazywa klatki ZDJĘTE. Zmierzone firsthandem na zaznaczeniu 711 klatek.

    Czasownik należy do GESTU: przywrócenie „oddaje" obiekt, więc „zdjęto z" byłoby tam nieprawdą
    o kierunku zapisu.

    Falsyfikator: przywróć w katalogu `object_canons` samo `": {canons}"` → pierwsza asercja
    czerwienieje; podaj przywracaniu ten sam klucz co cofnięciu → czerwienieje druga."""
    v, con = obj_view
    v.refresh()
    _zaznacz(v, [1, 2, 3])                        # 3 = light z nagłówka, gest go NIE tknie
    msgs = []
    v.status_message.connect(msgs.append)
    v._on_object_clear()
    assert "z nagłówka/regionu: 1 · zdjęto z: NGC6960" in msgs[-1], msgs[-1]

    _zaznacz(v, [1, 2])
    v._on_object_restore()
    assert "oddano: NGC6960" in msgs[-1], msgs[-1]
    assert "zdjęto z" not in msgs[-1], msgs[-1]


def test_recepta_powrotu_NIE_wskazuje_gestu_ktory_zawezenia_NIE_zdejmie(obj_view):
    """GRANICA FC-2 - recepta musi być WYKONALNA. „× Wyczyść zbiór" zdejmuje facety i filtr,
    ale flagi perspektywy zostawia (`_on_clear_selection`), więc w perspektywie z trimem
    wskazanie tego przycisku byłoby receptą, po której nic się nie odsłoni. Repo dostało tę klasę
    już raz, przy komunikacie o konflikcie („zawęź do dwóch", gdy zawężenie nic nie dawało).

    Przypadek jest TYPOWY, nie brzegowy: klatka po przywróceniu ma obiekt, więc do „Do przeglądu"
    nie należy - zdanie po geście bywa wtedy jedynym potwierdzeniem, że zapis się udał.

    Falsyfikator: zwróć w `_recepta_powrotu_do_widoku` zawsze `..._set` → asercja o nieobecności
    przycisku czerwienieje."""
    from horreum.gui import i18n
    v, con = obj_view
    v.refresh()
    _zaznacz(v, [1, 2])
    v._on_object_clear()

    v.apply_perspective("Do przeglądu")            # trim, którego przycisk zbioru nie tyka
    _zaznacz(v, [1, 2])
    raporty, recepty = _sluchaj_paska(v)
    v._on_object_restore()

    assert "poza widokiem: 2" in raporty[-1], raporty[-1]
    assert i18n.t("perspective.review") in recepty[-1], recepty[-1]
    assert i18n.t("grid.sel.clear_set") not in recepty[-1], recepty[-1]

    v.apply_perspective("Przegląd")                # …wykonaj receptę
    widoczne = {r["frame_id"] for r in v.model._rows if isinstance(r, dict) and "frame_id" in r}
    assert {1, 2} <= widoczne, "recepta wykonana, a klatki się nie odsłoniły"


def test_przy_DWOCH_zawezeniach_recepta_podaje_JEDEN_gest_ktory_zdejmuje_oba(obj_view):
    """Perspektywa z trimem PLUS facet - układ, w którym pierwsza wersja tej paczki kazała zrobić
    dwa gesty. Przełączenie perspektywy przepisuje także facety i filtr (`_on_perspective`),
    a „Przegląd" nie niesie ani trimu, ani filtra, więc jeden gest odsłania wszystko.

    Bramka pilnuje przy okazji, że recepta nie proponuje wtedy przycisku zbioru: on zdejmuje
    połowę zawężenia, więc po jego kliknięciu klatki DALEJ by nie wróciły.

    Falsyfikator: w `_rodzaj_recepty_powrotu` postaw `_zbior_zawezony()` przed `_trim_aktywny()`
    → recepta wraca do wariantu, który nie odsłania."""
    from horreum.gui import i18n
    v, con = obj_view
    v.refresh()
    _zaznacz(v, [1, 2])
    v._on_object_clear()

    v.apply_perspective("Do przeglądu")
    # Facet NA WIERZCHU trimu, i celowo po INNEJ osi niż obiekt: gdyby zawężał po obiekcie,
    # nagrobek (object_id NULL) wypadłby z widoku już przed gestem i układu by nie było.
    v._facet_state = {"kind": {"in": [["light", "light"]]}}
    v.refresh()
    _zaznacz(v, [1, 2])
    assert len(v._selected_data_rows()) == 2, "oba zawężenia zjadły cel - bramka nie odtwarza układu"
    raporty, recepty = _sluchaj_paska(v)
    v._on_object_restore()

    assert "poza widokiem: 2" in raporty[-1], raporty[-1]
    assert i18n.t("perspective.review") in recepty[-1], recepty[-1]
    assert i18n.t("grid.sel.clear_set") not in recepty[-1], recepty[-1]

    v.apply_perspective("Przegląd")
    widoczne = {r["frame_id"] for r in v.model._rows if isinstance(r, dict) and "frame_id" in r}
    assert {1, 2} <= widoczne, "jeden gest miał zdjąć OBA zawężenia"


def test_liczba_poza_widokiem_liczy_CZESC_zaznaczenia_nie_wszystko(obj_view):
    """Liczba ma być POMIAREM, nie sygnałem zero-jedynkowym. Bramka wytwarza układ, w którym część
    zaznaczenia zostaje na ekranie, a część wypada - błędne liczenie (np. „wszystko albo nic"
    czy pomyłka o markery grup) daje wtedy inną liczbę, a przy pełnym wypchnięciu przechodzi.

    Klatka 3 ma obiekt z NAGŁÓWKA, więc gest jej nie tyka i zostaje w facecie; nagrobki 1 i 2
    z niego wypadają.

    Falsyfikator: policz `poza` jako `len(zaznaczone)` zamiast różnicy → asercja o „: 2"
    czerwienieje na „: 3"."""
    v, con = obj_view
    v.apply_object_facet([(5, "NGC6960")])
    _zaznacz(v, [1, 2, 3])
    msgs = []
    v.status_message.connect(msgs.append)
    v._on_object_clear()

    widoczne = {r["frame_id"] for r in v.model._rows if isinstance(r, dict) and "frame_id" in r}
    assert 3 in widoczne and not ({1, 2} & widoczne), "układ mieszany nie powstał"
    assert "poza widokiem: 2" in msgs[-1], msgs[-1]


def test_KAZDA_recepta_powrotu_ma_klucz_w_katalogu(obj_view):
    """BRAMKA KLASY, nie sztuki (bramka pakietu, soczewka repo). Recepty wracają jako KLUCZE
    z gałęzi `_recepta_powrotu_do_widoku`, a kolektor bramki i18n zbiera wyłącznie literały
    podane wprost do `i18n.t(...)` - więc literówka w którejkolwiek gałęzi renderuje na pasku
    stanu surowy klucz i żadna istniejąca bramka tego nie łapie.

    Falsyfikator: przekręć literę w którymkolwiek zwrocie `_recepta_powrotu_do_widoku`
    → ten test czerwienieje, zanim zobaczy to użytkownik."""
    from horreum.gui.i18n_catalog import CATALOG
    v, _ = obj_view
    warianty = [(False, False), (True, False), (False, True), (True, True)]
    zebrane = set()
    for trim, zbior in warianty:
        # PRAWDZIWA FLAGA PERSPEKTYWY, nie zapamiętany wynik (BP-4): trim liczy się od tej zmiany
        # w miejscu użycia, więc bramka ustawia to, co ustawiłaby perspektywa.
        v._only_review = trim
        v._facet_state = {"object": {"in": [[5, "NGC6960"]]}} if zbior else {}
        wynik = v._recepta_powrotu_do_widoku()
        if wynik is None:
            assert not trim and not zbior, "brak recepty przy realnym zawężeniu"
            continue
        klucz, kwargi = wynik
        assert klucz in CATALOG, f"recepta pokazałaby surowy klucz: {klucz}"
        assert i18n_t_bez_wyjatku(klucz, kwargi) != klucz
        zebrane.add(klucz)
    assert len(zebrane) == 2, f"gałęzie recepty zeszły się do: {zebrane}"


def i18n_t_bez_wyjatku(klucz, kwargi):
    from horreum.gui import i18n
    return i18n.t(klucz, **kwargi)


def test_OS_ZYWOTNOSCI_tez_mowi_gdzie_podzialy_sie_klatki(obj_view, monkeypatch):
    """Ten sam człon na DRUGIEJ osi zaznaczenia (bramka pakietu, soczewka repo). Tu wypchnięcie
    celu nie jest przypadkiem brzegowym, tylko REGUŁĄ: wycofanie zdejmuje klatkę z kubełków
    roboczych i z perspektywy „Zniknięte", czyli dokładnie z widoku, w którym się jej szukało.
    Zdanie po geście „bywa jedynym śladem, że gest się odbył" - i milczało o tym, gdzie klatka
    się podziała.

    Falsyfikator: zdejmij `_czlon_poza_widokiem` z `_po_gescie_klatki` → asercja czerwienieje,
    a zdanie wraca do potwierdzania zapisu na klatce, której na ekranie nie ma."""
    from PySide6.QtWidgets import QMessageBox
    from horreum.gui import i18n
    v, con = obj_view
    con.execute("UPDATE location SET present = 0 WHERE frame_id = 3")   # plik zniknął z dysku
    con.commit()
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)

    v.apply_perspective(grid_mod.PRESET_VANISHED)
    _zaznacz(v, [3])
    assert len(v._selected_data_rows()) == 1, "klatka nie weszła do perspektywy - bramka nie odtwarza układu"
    raporty, recepty = _sluchaj_paska(v)
    v._on_frame_retire()

    assert con.execute("SELECT retired_at FROM frame WHERE id = 3").fetchone()[0] is not None
    assert "poza widokiem: 1" in raporty[-1], raporty[-1]
    assert i18n.t("perspective.review") in recepty[-1], recepty[-1]


def test_PRESET_wskazywany_przez_recepte_jest_naprawde_bez_zawezenia():
    """Recepta obiecuje, że „Przegląd" odsłoni WSZYSTKO. Obietnica stoi na tym, że ten preset nie
    niesie ani filtra, ani żadnej flagi `only_*` - a rodzina `only_*` ma w tym repo udokumentowaną
    historię rozjazdów. Bramka pilnuje przesłanki, nie skutku.

    Falsyfikator: dopisz `only_review: True` do wskazywanego presetu → test czerwienieje."""
    spec = grid_mod.PRESETS[grid_mod._PRESET_CZYSTY]
    assert spec.get("filter") is None, "preset recepty niesie filtr"
    assert not [k for k in spec if k.startswith("only_")], f"preset recepty niesie trim: {spec}"


def test_przywrocenie_ODDAJE_obiekt_JEDNYM_gestem_po_masowym_cofnieciu(obj_view):
    """DROGA POWROTU (R-S2b-3, człon trzeci) — pełny przepływ przez POWIERZCHNIĘ: cofnij masowo,
    a potem przywróć jednym kliknięciem. Składa się z członem pierwszym: zaznaczenie po cofnięciu
    ZOSTAJE, więc cel gestu naprawczego jest już wskazany i nie trzeba go odtwarzać.

    Falsyfikator: zdejmij `_przywroc_zaznaczenie` → gest przywracania trafia w pustkę i mówi
    „zaznacz klatki", zamiast oddać obiekt."""
    v, con = obj_view
    v.refresh()
    _zaznacz(v, [1, 2])
    v._on_object_clear()
    assert con.execute("SELECT count(*) FROM frame WHERE object_source = 'user_cleared'"
                       ).fetchone()[0] == 2

    v._update_count()
    assert v.sel_bar.act_restore.isEnabled(), "pozycja wygaszona nad żywym nagrobkiem"
    msgs = []
    v.status_message.connect(msgs.append)
    v._on_object_restore()

    zrodla = dict(con.execute("SELECT COALESCE(object_source,'—'), count(*) FROM frame "
                              "GROUP BY 1").fetchall())
    assert zrodla.get("user_cleared") is None and zrodla["user"] == 2
    assert "Przywrócono przypisanie na 2 z 2 klatek" in msgs[-1] and ": NGC6960" in msgs[-1]


def test_pozycja_przywracania_GASNIE_gdy_nie_ma_czego_przywrocic(obj_view):
    """Uczciwy disabled trzeciej pozycji — liczony z read-modelu, nie z domysłu. Kontrolka zostaje
    żywa (są inne akcje), bo menu tłumaczące wygaszoną pozycję mówi więcej niż wygaszony przycisk.

    Człon tooltipu MILCZY przy zerze: „do przywrócenia: 0" mówiłoby o czymś, czego w zaznaczeniu
    nie ma — to ta sama reguła, którą R-S3-8 postawiło dla gotowych obrazów."""
    v, con = obj_view
    v.refresh()
    _zaznacz(v, [1, 2])
    v._update_count()
    assert not v.sel_bar.act_restore.isEnabled()
    assert "do przywrócenia" not in v.sel_bar.btn_object.toolTip()

    v._on_object_clear()
    v._update_count()
    assert v.sel_bar.act_restore.isEnabled()
    assert "do przywrócenia: 2" in v.sel_bar.btn_object.toolTip()


def test_przywrocenie_nagrobka_BEZ_pamieci_mowi_prawde_i_nic_nie_pisze(obj_view):
    """Nagrobek sprzed migracji 0017 (baza-dawca) wygląda na ekranie identycznie jak ten z pamięcią,
    więc milczenie kazałoby userowi zgadywać, czy gest nie zadziałał, czy nie miał na czym.

    Od FC-6 uczciwe zero mówi GRAMATYKĄ SĄSIADÓW („0 z N" plus rozbicie), a nie osobnym zdaniem
    „Nie ma czego przywrócić" - stąd zmiana asercji; fakt (zero zapisu, nazwana przyczyna) ten sam."""
    v, con = obj_view
    v.refresh()
    _zaznacz(v, [1])
    v._on_object_clear()
    con.execute("UPDATE frame SET object_cleared_id = NULL WHERE id = 1")
    con.commit()

    przed = con.execute("SELECT count(*) FROM event").fetchone()[0]
    msgs = []
    v.status_message.connect(msgs.append)
    _zaznacz(v, [1])
    v._on_object_restore()
    assert con.execute("SELECT count(*) FROM event").fetchone()[0] == przed
    assert "Przywrócono przypisanie na 0 z 1 klatek" in msgs[-1], msgs[-1]
    assert "bez zapamiętanego obiektu: 1" in msgs[-1], msgs[-1]


def test_populacja_MIESZANA_nie_wymazuje_potwierdzenia_gestu(obj_view):
    """POPULACJA MIESZANA MA JEDNO ZDANIE, NIE DWA (bramka pakietu 0810, zarzut Fable Z#1).

    Odbiornikiem `status_message` jest jeden `showMessage` (`app._flash`), więc druga emisja w tym
    samym obrocie pętli WYMAZUJE pierwszą — user po UDANYM przywróceniu widziałby wyłącznie
    „pominięto N bez zapamiętanego obiektu", a potwierdzenia gestu nie widziałby wcale. Kosztuje to
    akurat zdanie, które przy tym geście bywa JEDYNYM potwierdzeniem: klatka przywrócona wypada
    z perspektywy „Do przeglądu", więc z ekranu znika.

    Od FC-6 nagrobek bez pamięci jest CZŁONEM rozbicia w tym jednym zdaniu, a mianownik liczy całe
    zaznaczenie - stąd „1 z 2" zamiast dawnego „1 z 1" i człon zamiast zdania „Pominięto N…".

    Falsyfikator: wyślij nagrobki bez pamięci drugim `status_message.emit` zamiast członem
    rozbicia → `msgs[-1]` przestaje nieść „Przywrócono", choć zapis się udał."""
    v, con = obj_view
    v.refresh()
    _zaznacz(v, [1, 2])
    v._on_object_clear()
    con.execute("UPDATE frame SET object_cleared_id = NULL WHERE id = 2")   # nagrobek sprzed 0017
    con.commit()

    msgs = []
    v.status_message.connect(msgs.append)
    _zaznacz(v, [1, 2])
    v._on_object_restore()

    assert con.execute("SELECT object_source FROM frame WHERE id = 1").fetchone()[0] == "user"
    assert "Przywrócono przypisanie na 1 z 2 klatek" in msgs[-1], "potwierdzenie gestu wymazane"
    assert "· bez zapamiętanego obiektu: 1" in msgs[-1], "drugi fakt zgubiony przy sklejaniu"


def _zaznaczenie_do_przywrocenia(con, *, pamiec=(), bez_pamieci=0, z_obiektem=0, darki=0,
                                 bez_obiektu=0, start_id=20):
    """Zaznaczenie o ZNANYM składzie per fakt dla gestu przywracania (FC-6). Surowy SQL, jak
    `_lighty_z_obiektami`. `pamiec` = kanony: po jednym nagrobku Z PAMIĘCIĄ na pozycję (powtórzony
    kanon = kilka klatek w jednej grupie). Obiekt z RĘKI dostaje `NGC6960` z fikstury `obj_view`.
    Zwraca id wszystkich klatek w kolejności wstawienia."""
    wiersze = ([("light", None, "user_cleared", kanon) for kanon in pamiec]
               + [("light", None, "user_cleared", None)] * bez_pamieci
               + [("light", 5, "user", None)] * z_obiektem
               + [("dark", None, None, None)] * darki
               + [("light", None, None, None)] * bez_obiektu)
    oid = {}
    for kanon in dict.fromkeys(pamiec):
        oid[kanon] = 200 + len(oid)
        con.execute("INSERT INTO object(id, canon, catalog, kind) VALUES (?,?,'NGC','deep_sky')",
                    (oid[kanon], kanon))
    ids = []
    for fid, (kind, object_id, source, kanon) in enumerate(wiersze, start=start_id):
        con.execute("INSERT INTO frame(id, kind, filetype, sha1_data, first_seen_at, object_id, "
                    "object_source, object_cleared_id) VALUES (?, ?, 'raw', ?, ?, ?, ?, ?)",
                    (fid, kind, f"sha-fc6-{fid}", NOW, object_id, source, oid.get(kanon)))
        con.execute("INSERT INTO header(frame_id, raw_json) VALUES (?, '{}')", (fid,))
        ids.append(fid)
    con.commit()
    return ids


def test_przywrocenie_liczy_CALE_zaznaczenie_z_rozbiciem_per_fakt(obj_view):
    """FC-6 / R-S2b-13 - defekt zmierzony na ekranie: pasek „120 zaznaczonych", a zdanie po geście
    „Przywrócono przypisanie na 30 z 30 klatek", podczas gdy sąsiedni gest tej samej osi w tej
    samej sytuacji mówi „6 z 354 · z nagłówka/regionu: 348". Klatki spoza grup nie liczyły się
    nigdzie, więc „z M" kłamało o zaznaczeniu.

    Skład (pomniejszony, kształt ten sam): nagrobki z pamięcią w DWÓCH grupach, nagrobki bez
    pamięci, klatki z obiektem ręki, darki, lighty bez obiektu. Człon „nothing" mówi czasownikiem
    GESTU („przywrócić"), nie cofnięcia.

    Falsyfikator: składaj gest od `repo.ObjectGesture()` zamiast `ObjectGesture(**pominiete)`
    → zdanie wraca do „6 z 6" i gubi trzy człony rozbicia."""
    v, con = obj_view
    ids = _zaznaczenie_do_przywrocenia(con, pamiec=["NGC7000"] * 4 + ["IC443"] * 2,
                                       bez_pamieci=2, z_obiektem=5, darki=2, bez_obiektu=3)
    v.refresh()
    _zaznacz(v, ids)
    assert len(v._selected_data_rows()) == len(ids) == 18, "fikstura nie weszła do widoku"
    msgs = []
    v.status_message.connect(msgs.append)
    v._on_object_restore()

    assert "Przywrócono przypisanie na 6 z 18 klatek" in msgs[-1], msgs[-1]
    assert "· nie było czego przywrócić: 8" in msgs[-1], msgs[-1]      # 5 z obiektem + 3 bez
    assert "· bez zapamiętanego obiektu: 2" in msgs[-1], msgs[-1]
    assert "· kalibracja: 2" in msgs[-1], msgs[-1]
    assert "cofać" not in msgs[-1], "czasownik cofnięcia pod zdaniem przywracania"
    assert "oddano: IC443, NGC7000" in msgs[-1], msgs[-1]


def test_przywrocenie_przy_ZERZE_grup_mowi_zdaniem_sasiadow(obj_view):
    """FC-6: zero grup nie ma już osobnego zdania („Nie ma czego przywrócić…"). Sąsiad w tej samej
    sytuacji mówi „Cofnięto … 0 z N · nie było czego cofać: N", więc przywracanie mówi „0 z N"
    z rozbiciem - jedna gramatyka osi, jeden właściciel zdania (`_po_gescie_osi`).

    Fikstura bez nagrobków: dwa lighty ze ścieżki, jeden z nagłówka, dark. Zdanie porównujemy
    W CAŁOŚCI, bo pytanie brzmi też „czego w nim NIE MA" - drugiej emisji ani ogona.

    Falsyfikator: przywróć wczesny `return` przy `not grupy` z osobnym zdaniem → asercja równości
    czerwienieje."""
    v, con = obj_view
    v.refresh()
    _zaznacz(v, [1, 2, 3, 4])
    przed = con.execute("SELECT count(*) FROM event").fetchone()[0]
    msgs = []
    v.status_message.connect(msgs.append)
    v._on_object_restore()

    assert msgs[-1] == ("Przywrócono przypisanie na 0 z 4 klatek · kalibracja: 1"
                        " · nie było czego przywrócić: 3"), msgs[-1]
    assert con.execute("SELECT count(*) FROM event").fetchone()[0] == przed


def test_NIEZMIENNIK_trzy_gesty_osi_licza_CALE_zaznaczenie(obj_view, monkeypatch):
    """FC-6: dla KAŻDEGO zaznaczenia `assigned + skipped == len(ids)` u wszystkich trzech gestów
    osi - to jest treść „jednej gramatyki", a nie zbieżność napisów. Gesty idą przez HANDLERY
    powierzchni (okno nadania podmienione atrapą, która akceptuje), a gest łapiemy na wejściu
    do `_po_gescie_osi`, czyli tam, gdzie z niego powstaje zdanie.

    Kolejność gestów przeprowadza zaznaczenie przez różne stany (nagrobki z pamięcią i bez,
    obiekt ręki, ścieżka, nagłówek, kalibracja, klatki bez obiektu), więc niezmiennik jest pytany
    w każdym z nich, a nie w jednym wygodnym.

    Falsyfikator: zdejmij doliczanie `pominiete` w `_on_object_restore` → pierwszy gest łamie
    niezmiennik (6 zamiast 22)."""
    from PySide6.QtWidgets import QDialog
    v, con = obj_view

    class _Okno:
        def __init__(self, *a, **kw):
            self.selected = ("NGC6960", "NGC", "deep_sky", None)

        def exec(self):
            return QDialog.Accepted

    monkeypatch.setattr("horreum.gui.grid.AssignObjectDialog", _Okno)
    gesty = []
    oryginal = v._po_gescie_osi

    def _podsluch(klucz, gest, **kw):
        gesty.append((klucz, gest))
        return oryginal(klucz, gest, **kw)

    monkeypatch.setattr(v, "_po_gescie_osi", _podsluch)
    ids = [1, 2, 3, 4] + _zaznaczenie_do_przywrocenia(
        con, pamiec=["NGC7000"] * 4 + ["IC443"] * 2, bez_pamieci=2, z_obiektem=5, darki=2,
        bez_obiektu=3)
    v.refresh()
    for gest_handler in (v._on_object_restore, v._on_object_clear, v._on_object_restore,
                         v._on_object_name):
        _zaznacz(v, ids)
        assert len(v._selected_data_rows()) == len(ids), "cel gestu nie jest całym zaznaczeniem"
        gest_handler()
    assert [k for k, _g in gesty] == ["grid.sel.object_restored", "grid.sel.object_cleared",
                                      "grid.sel.object_restored", "grid.sel.object_named"]
    for klucz, g in gesty:
        assert g.assigned + g.skipped == len(ids), (klucz, g)
    assert gesty[0][1].assigned == 6 and gesty[2][1].assigned > 0, "gesty nic nie ruszyły"


def test_przywrocenie_po_BLEDZIE_grupy_liczy_reszte_jako_odmowe_klingi(obj_view, monkeypatch):
    """FC-6, drugi człon defektu: po `break` na `ValueError` klatki grupy, która padła, i grup po
    niej nie liczyły się nigdzie. Grupa, która padła, wycofała się w całości (`_immediate`),
    a dalsze do klingi nie doszły - żadna z nich nie jest zapisana.

    R-S2b-13 (bramka pakietu): do tej poprawki ta bramka pinowała je jako DRYF („zmieniły się
    w międzyczasie"). `ValueError` klingi to jednak także konflikt aliasu - nic się nie zmieniło,
    klinga odmówiła - więc zdanie kłamało o stanie. Liczą się jako `skipped_failed` („nie zapisano,
    klinga odmówiła"), a dryf zostaje przy zerze.

    Grupy idą po kanonie (IC443, LMC, M42); klinga pada na LMC → IC443 zapisany, LMC (2) i M42 (1)
    liczą się jako odmowa klingi.

    Falsyfikator: zdejmij doliczenie przed `break` → „1 z 1" zamiast „1 z 4"; dolicz resztę
    z powrotem do `skipped_drift` → wraca człon dryfu i asercja jego braku czerwienieje."""
    from PySide6.QtWidgets import QMessageBox
    v, con = obj_view
    ids = _zaznaczenie_do_przywrocenia(con, pamiec=["IC443", "LMC", "LMC", "M42"])
    v.refresh()
    prawdziwa = grid_mod.repo.user_assign_object

    def _pada_na_lmc(con_, **kw):
        if kw["canon"] == "LMC":
            raise ValueError("frame:0 nie istnieje")
        return prawdziwa(con_, **kw)

    monkeypatch.setattr(grid_mod.repo, "user_assign_object", _pada_na_lmc)
    ostrzezenia = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: ostrzezenia.append(a))
    _zaznacz(v, ids)
    msgs = []
    v.status_message.connect(msgs.append)
    v._on_object_restore()

    assert ostrzezenia, "błąd klingi przeszedł bez słowa"
    assert "Przywrócono przypisanie na 1 z 4 klatek" in msgs[-1], msgs[-1]
    assert "· nie zapisano, klinga odmówiła: 3" in msgs[-1], msgs[-1]
    assert "zmieniły się w międzyczasie" not in msgs[-1], msgs[-1]


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


def test_tooltip_liczy_stosy_TYKALNE_a_nie_wszystkie(obj_view):
    """BRAMKA PAKIETU 0810, zarzut 1 - REGRESJA ZNACZENIA wniesiona przez R-S3-8.

    Człon „w tym gotowe obrazy" jechał na `stacks`, czyli na „ile stosów JEST w zaznaczeniu",
    a stoi w zdaniu o SKUTKU, obok „do nazwania / do cofnięcia". Stos z nazwą ze źródła mocnego
    (`header`, `catalog_xref`, `common_name`) nie jest ani do nazwania, ani do cofnięcia - gest
    go NIE TKNIE, a tooltip go liczył.

    To nie jest przypadek brzegowy, tylko dominujący: zmierzone na żywym archiwum **181 ze 193
    stosów jest nietykalnych**, więc człon kłamałby w 94% realnych zaznaczeń - w powierzchni,
    która powstała po to, żeby powiedzieć prawdę PRZED gestem.

    Falsyfikator: wróć w `_update_count` do `stan["stacks"]` → druga asercja czerwienieje."""
    from horreum.gui import i18n
    v, con = obj_view
    _dodaj_stos(con, 14, src="header")          # nazwa z KARTY - gest jej nie tknie
    v.refresh()

    _zaznacz(v, [1, 2, 14])
    v._update_count()
    stan = queries.selection_object_state(con, [1, 2, 14])
    assert (stan["stacks"], stan["stacks_touchable"]) == (1, 0),         "read-model musi rozróżniać, ile stosów JEST, od tego, ile gest RUSZY"
    assert v.sel_bar.btn_object.toolTip() == i18n.t(
        "grid.sel.object_tip_ready", namable=stan["namable"], clearable=stan["clearable"]),         "tooltip policzył stos, którego gest nie tknie"


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
    assert len(bar.btn_object.menu().actions()) == 3 + 1 + bar._RECENT_MAX
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


# ───────────────────────────── oś ŻYWOTNOŚCI klatki (D-OW-3/R2)

def test_wycofana_ma_wlasne_tlo_wlasna_komorke_i_swoje_miejsce_w_hierarchii():
    """Kolejność `if`-ów w `_base_cell` JEST regułą, a nie szczegółem: pełna hierarchia brzmi
    **zastąpiona > wycofana > zniknięta > duplikat** i wynika z jednego pytania — czy tu jest
    robota. Bez tego wiersz w perspektywie „Wycofane" byłby pomalowany i OPISANY jako zniknięty,
    czyli ekran wołałby o robotę, którą człowiek przed chwilą zamknął."""
    from horreum.gui.grid import GridTableModel, BASE_COLS
    from horreum.gui import grid as grid_mod
    wspolne = {"kind": "light", "camera_model": None, "telescope_label": None,
               "telescop_canon": None, "object_canon": None, "object_raw": None,
               "filter_canon": None, "date_obs": None, "exptime": None, "filetype": "fits",
               "object_source": None, "object_cleared_id": None, "last_verified_at": None}
    base = [
        {"frame_id": 1, "path": "/a/zywa.fits", "present": 1, "n_present": 1,
         "superseded_by": None, "retired_at": None, **wspolne},
        {"frame_id": 2, "path": "/a/znikla.fits", "present": 0, "n_present": 0,
         "superseded_by": None, "retired_at": None, **wspolne},
        {"frame_id": 3, "path": "/a/wycofana.fits", "present": 0, "n_present": 0,
         "superseded_by": None, "retired_at": "2026-08-11T10:00:00+00:00", **wspolne},
        # klatka JEDNOCZEŚNIE zastąpiona i wycofana — stan możliwy, więc hierarchia musi go
        # rozstrzygnąć: pierwszeństwo ma to, co mówi DOKĄD poszła treść
        {"frame_id": 4, "path": None, "present": None, "n_present": 0,
         "superseded_by": 99, "retired_at": "2026-08-11T10:00:00+00:00", **wspolne},
    ]
    m = GridTableModel()
    m.set_data(base, pivot_mod.build_pivot([1, 2, 3, 4], [], []), [])
    kol = [k for _, k in BASE_COLS].index("path")
    teksty = [m.data(m.index(i, kol), Qt.DisplayRole) for i in range(m.rowCount())]

    i_wyc = next(i for i, t in enumerate(teksty) if t and "wycofana.fits" in t)
    i_znik = teksty.index("znikla.fits")
    i_zast = teksty.index("zastąpiona przez #99")
    i_zywa = teksty.index("zywa.fits")

    # MÓWI TO W KOMÓRCE, nie tylko tłem (user bywa daltonistą albo ma inny motyw)
    assert "(wycofana)" in teksty[i_wyc]
    # …i mówi to PRZED nazwą, bo inaczej NIE MÓWI TEGO WCALE. Kolumna „Ścieżka" startuje na
    # domyślnej szerokości sekcji, a nazwa pliku archiwum jest od niej kilkakrotnie szersza,
    # więc marker doklejony z tyłu ginął w elizji ZAWSZE (firsthand 0811, wizytator-qt) —
    # dokładnie tak, jak zginął kiedyś sufiks „×N" duplikatów, zanim stał się prefiksem.
    # Sam `in` tego nie pinuje: przechodzi też dla sufiksu, czyli dla wersji z defektem.
    assert teksty[i_wyc].startswith("(wycofana)"), (
        "marker wycofania musi stać PRZED nazwą — jako sufiks nie dociera do ekranu")
    assert m.data(m.index(i_wyc, 0), Qt.BackgroundRole) == grid_mod._COLORS["retired_bg"]
    # …i NIE jest malowana jak zniknięta, choć obecnej kopii nie ma tak samo
    assert m.data(m.index(i_wyc, 0), Qt.BackgroundRole) != grid_mod._COLORS["vanished_bg"]
    # tooltip niesie DATĘ (jedyny fakt o wycofaniu nie do odtworzenia skądinąd) i drogę powrotu
    tip = m.data(m.index(i_wyc, kol), Qt.ToolTipRole)
    assert "2026-08-11 10:00" in tip and "Przywróć" in tip
    # ZASTĄPIONA bije WYCOFANĄ: obie mówią „nie ma tu roboty", ale tylko jedna mówi DOKĄD
    assert m.data(m.index(i_zast, 0), Qt.BackgroundRole) == grid_mod._COLORS["superseded_bg"]
    # regresja obu sąsiadów
    assert m.data(m.index(i_znik, 0), Qt.BackgroundRole) == grid_mod._COLORS["vanished_bg"]
    assert m.data(m.index(i_zywa, 0), Qt.BackgroundRole) is None


def test_perspektywa_wycofane_jest_jedyna_droga_do_gestu_powrotu(view, gcon):
    """Perspektywa nie jest tu wygodą, tylko DRUGĄ POŁOWĄ ODWRACALNOŚCI: gest przywrócenia bierze
    cel z zaznaczenia, a zaznaczyć można wyłącznie to, co widać."""
    from horreum.gui.grid import PRESET_RETIRED
    from horreum import repo
    gcon.execute("UPDATE frame SET retired_at = ? WHERE id = 4", ("2026-08-11T10:00:00+00:00",))
    gcon.commit()
    view.apply_perspective(PRESET_RETIRED)
    assert view._frame_ids == [4]
    # …a klatka wycofana wypadła z perspektywy, w której dotąd tkwiła
    view.apply_perspective("Zniknięte")
    assert view._frame_ids == []


def test_pasek_gasnie_UCZCIWIE_gdy_pliki_zaznaczonych_klatek_zyja(view):
    """Wygaszona kontrolka bez powodu wygląda na usterkę. Rozróżnienie „nic nie zaznaczono" od
    „zaznaczyłeś klatki, których pliki żyją" jest tu całą treścią: drugie to OCHRONA, która
    zadziałała, i user ma prawo to wiedzieć."""
    from horreum.gui.grid import _frame_gate_reason
    assert _frame_gate_reason(0, 0) == "grid.sel.frame_tip_empty"
    assert _frame_gate_reason(3, 3) == "grid.sel.frame_tip_alive"
    assert _frame_gate_reason(3, 0) == "grid.sel.frame_tip_none"
    view.sel_bar.set_frame_actions(retirable=0, restorable=0, reason="grid.sel.frame_tip_alive")
    assert view.sel_bar.btn_frame.isEnabled() is False
    assert "istnieją na dysku" in view.sel_bar.btn_frame.toolTip()


def test_droga_powrotu_jest_WIDOCZNA_take_gdy_nie_ma_czego_przywrocic(view):
    """Ta sama reguła, co przy „Przywróć cofnięte przypisanie": pozycja widoczna ZAWSZE, wygaszona
    gdy pusta — o odwracalności trzeba wiedzieć PRZED pomyłką. Tu waży podwójnie, bo wycofanie
    zdejmuje klatkę z oczu, więc bez tej pozycji nie ma skąd wiedzieć, że gest się cofa."""
    view.sel_bar.set_frame_actions(retirable=2, restorable=0)
    assert view.sel_bar.act_frame_restore.isVisible() is True   # QAction: isVisible, nie isHidden
    assert view.sel_bar.act_frame_restore.isEnabled() is False
    assert view.sel_bar.act_retire.isEnabled() is True
    assert view.sel_bar.btn_frame.isEnabled() is True


# ---------- D-V-9a: perspektywa „Brakujące kopie" + bramka na enumerację przełączników ----------

def test_predykat_brakujacej_kopii_odroznia_sie_od_trzech_sasiadow(gcon):
    """Czwarty stan, nie odmiana trzech poprzednich. Fikstura ma wszystkie naraz: f1 = DWIE żywe
    kopie (duplikat, nadmiar), f4 = jedyna kopia martwa (zniknięta, robota), f5 = żywa + martwa
    (brakująca kopia). Gdyby predykat pytał tylko o `present=0`, wchłonąłby f4 i zamienił listę
    „nic nie zginęło" w drugą listę „poszukaj plików"."""
    _zasiej_dwa_adresy(gcon)
    assert queries.missing_copy_frame_ids(gcon) == {5}
    assert queries.vanished_frame_ids(gcon) == {4}, "zniknięta ZOSTAJE u siebie"
    assert queries.dup_frame_ids(gcon) == {1}, "duplikat ZOSTAJE u siebie"


_NOW_KLINGI = "2026-08-14T10:00:00+00:00"


def _klatka_klinga(con, sha, zywe=(), martwe=()):
    """Klatka z kopiami ŻYWYMI i MARTWYMI - wyłącznie KLINGĄ (`repo`), nigdy `UPDATE`-em (D-V-9e).

    Konwencja domu (`test_frame_retire.py`): stan budujemy drogą, którą idzie program, bo inaczej
    test pinuje własny SQL zamiast zachowania - a fikstura potrafi wtedy wytworzyć stan, którego
    klinga ODMAWIA (zastąpiona z obecną kopią), i przetestować ukrywanie złamanego inwariantu."""
    from horreum import repo
    fid, _ = repo.upsert_frame(con, sha1_data=sha, kind="master_light", filetype="xisf",
                               camera_id=None, now=_NOW_KLINGI)
    for path in martwe:
        lid, _ = repo.add_location(con, frame_id=fid, volume="V", path=path, now=_NOW_KLINGI)
        repo.mark_location_vanished(con, location_id=lid, expected_path=path, root="/",
                                    run_id="test-klinga", now=_NOW_KLINGI)
    for path in zywe:
        repo.add_location(con, frame_id=fid, volume="V", path=path, now=_NOW_KLINGI)
    return fid


def _wycofana_z_powrotem(con, sha, *, martwa, wrocily=()):
    """Klatka WYCOFANA, której plik wrócił - stan „a plik wrócił" (G2-7d) drogą programu: jedyna
    kopia znika, ręka wycofuje, a re-skan znajduje tę samą treść pod NOWĄ ścieżką (`add_location`
    - reguła N-lokacji; wycofania nic nie gasi, bo „ręka nietykalna"). Martwa kopia zostaje."""
    from horreum import repo
    fid = _klatka_klinga(con, sha, martwe=[martwa])
    assert repo.retire_frames(con, frame_ids=[fid], now=_NOW_KLINGI).done == 1
    for path in wrocily:
        repo.add_location(con, frame_id=fid, volume="V", path=path, now=_NOW_KLINGI)
    return fid


def test_zastapiona_wypada_z_brakujacych_kopii_na_stanie_z_klingi(gcon):
    """D-V-9e: guard zastąpienia pinowany na stanie, który program REALNIE umie wyprodukować.

    Do tej zmiany fikstura stawiała `superseded_by` UPDATE-em na klatce z obecną kopią - stan,
    którego `repo.mark_superseded` odmawia, a `audit.supersede_invariants` liczy jako naruszenie.
    Tu zastąpienie przychodzi klingą PO zgaszeniu kopii, więc inwariant jest czysty (asercja
    niżej to pinuje), a klatka nie trafia do „Brakujących kopii": nie ma żywej kopii, której
    brakowałoby rodzeństwa, a jej historię zamknęła następczyni."""
    from horreum import audit, repo
    fid = _klatka_klinga(gcon, "zast", martwe=["/stare/a.xisf", "/stare/b.xisf"])
    assert repo.mark_superseded(gcon, frame_id=fid, superseded_by=1, now=_NOW_KLINGI) is True
    assert audit.supersede_invariants(gcon)["zastapiona_z_obecna_kopia"] == 0
    assert fid not in queries.missing_copy_frame_ids(gcon)
    assert fid in queries.superseded_frame_ids(gcon), "nie znika z oczu - ma swoją listę"


def test_wycofana_z_brakujaca_kopia_ZOSTAJE_w_brakujacych_kopiach(gcon):
    """D-V-9d: tooltip „wcześniejszy adres" i perspektywa „Brakujące kopie" liczą TEN SAM zbiór.

    Klatka wycofana, której plik wrócił pod nowym adresem, a stary dalej leży martwy, JEST klatką
    z brakującą kopią - fakt o kopii nie zależy od gestu ręki. Guard `retired_at IS NULL` wycinał
    ją z perspektywy, choć tooltip pokazywał jej historię przeprowadzki. Licznik Porządków czyta
    ten sam predykat, więc liczba i lista mówią to samo.

    Falsyfikator: przywróć `AND f.retired_at IS NULL` w `missing_copy_frame_ids` - klatka wypada
    i pierwsza asercja czerwienieje (a licznik Porządków pokazuje 0 przy niepustym tooltipie)."""
    fid = _wycofana_z_powrotem(gcon, "wyc", martwa="/stare/m.xisf", wrocily=["/nowe/m.xisf"])
    assert queries.missing_copy_frame_ids(gcon) == {fid}
    assert queries.tasks_state(gcon)["missing_copy_frames"] == 1
    assert queries.retired_conflict_frame_ids(gcon) == {fid}, "i dalej jest robotą konfliktu"
    # wycofana BEZ powrotu pliku (jedyna kopia martwa) do „Brakujących kopii" nie wchodzi -
    # nie ma żywej kopii, więc to nie jest ubytek jednej z kilku
    bez_pliku = _wycofana_z_powrotem(gcon, "wyc2", martwa="/stare/n.xisf")
    assert bez_pliku not in queries.missing_copy_frame_ids(gcon)


def test_brakujace_kopie_pokazuja_wycofana_Z_JEJ_znacznikiem(view, gcon):
    """D-V-9d na EKRANIE: wiersz w perspektywie „Brakujące kopie" tłumaczy się sam - znacznik
    wycofania stoi w komórce, a tooltip niesie i werdykt ręki, i wcześniejszy adres (dwa fakty
    o tej samej klatce, nie sprzeczność). Test idzie przez preset PO STAŁEJ, jak klik w Porządkach."""
    fid = _wycofana_z_powrotem(gcon, "wyc", martwa="/stare/m.xisf", wrocily=["/nowe/m.xisf"])
    view.apply_perspective(grid_mod.PRESET_MISSING_COPY)
    assert view._frame_ids == [fid]
    r = next(i for i, row in enumerate(view.model._rows) if row.get("frame_id") == fid)
    assert view.model.data(view.model.index(r, 0), Qt.DisplayRole).startswith(
        "(wycofana, plik wrócił)")
    tip = _path_tip(view, fid)
    assert "plik jest znów na dysku" in tip and "wcześniejszy adres: /stare/m.xisf" in tip


def test_perspektywa_brakujacych_kopii_przycina_grid(view, gcon):
    """Przełącznik `only_missing_copy` przepięty KOŃCEM DO KOŃCA: preset → flaga → trim w refresh.
    Test celuje w preset PO STAŁEJ, nie po napisie - dokładnie tak, jak robi to klik w Porządkach."""
    _zasiej_dwa_adresy(gcon)
    view.apply_perspective(grid_mod.PRESET_MISSING_COPY)
    assert [r["frame_id"] for r in view.model._data_rows] == [5]
    assert "brakującą kopią" in view.sel_bar.criteria_label.toolTip()


def test_wiersz_porzadkow_jest_KLIKALNY_ale_NIE_ROBOTA(gcon):
    """Trzeci stan wiersza (jak „Zastąpione"/„Wycofane"): MA dokąd prowadzić, ale jego liczba nigdy
    nie jest zadaniem - klatka żyje, nic nie zginęło i nic się nie pali. Gdyby wpadł do odznaki
    sidebara, 128 gotowych obrazów wołałoby o robotę, której nie ma."""
    _zasiej_dwa_adresy(gcon)
    assert queries.tasks_state(gcon)["missing_copy_frames"] == 1
    assert "missing_copy_frames" in tasks_mod._BEZ_ROBOTY
    cel = next(cel for klucz, _et, cel in tasks_mod._TASKS if klucz == "missing_copy_frames")
    assert cel == grid_mod.PRESET_MISSING_COPY, "wiersz musi celować w preset PO STAŁEJ"


def test_wiersz_historii_jest_WYSZARZONY_mimo_wlasnej_liczby(qapp, gcon):
    """Druga połowa stanu „nie robota" (bramka pakietu D-V-9a): `_BEZ_ROBOTY` gasiło odznakę
    i pogrubienie, ale KOLOR zależał wyłącznie od `n > 0`, więc wiersz historii stał na liście
    w pełnej czerni - a przy 128 jest tam największą liczbą i wzrok czyta go jako największy
    problem. Wyszarzenie znaczy w tej liście „nie ma tu roboty", nie „nie da się kliknąć":
    sąsiedni test dowodzi, że wiersz dalej prowadzi do perspektywy."""
    from horreum.gui import rows
    _zasiej_dwa_adresy(gcon)
    tv = tasks_mod.TasksView(gcon)
    try:
        tv.refresh_counts()
        it = next(tv.tasks.item(i) for i in range(tv.tasks.count())
                  if tv.tasks.item(i).data(Qt.UserRole) == "missing_copy_frames")
        assert it.data(rows.SECONDARY) == "1  ›", "wiersz ma NIEZEROWĄ liczbę i mimo to ma być szary"
        assert it.foreground().color() == tasks_mod._DIM["fg"]
        assert it.data(rows.STRONG) is False
        assert it.flags() & Qt.ItemIsEnabled, "szary NIE znaczy nieklikalny - to jest cała różnica"
    finally:
        tv.close()


def test_KAZDY_preset_ma_etykiete_i_zuzyta_flage():
    """BRAMKA NA ENUMERACJĘ (D-V-9a). Rodzina `only_*` ma UDOKUMENTOWANĄ historię regresji: rozjazd
    enumeracji wyprodukował kiedyś „Baza pusta" na pełnej bazie (`483df93`). Ta paczka POWTÓRZYŁA
    tę klasę błędu - przełącznik wpięty w osiem miejsc i pominięty w dziewiątym (`_PRESET_LABELS`),
    co wywaliło 116 testów `KeyError`-em. Znalezisko jednostkowe podniesione do kontroli:

      1. każdy preset ma etykietę wyświetlania - inaczej `KeyError` przy pierwszym renderze listy;
      2. etykieta jest KLUCZEM KATALOGU i18n - `_PRESET_LABELS` idzie do `i18n.t()` ZMIENNĄ, więc
         bramka kluczy literalnych (`test_klucze_call_site_podzbior_katalogu`) jest tu ślepa,
         a `i18n.t` na nieznanym kluczu nie rzuca - renderuje surowe `perspective.foo` na ekranie;
      3. każdy klucz `only_*` ze specyfikacji presetu ma WIERSZ W `_TRIMY`, a nie jest tylko
         wyzerowany w `__init__` - inaczej perspektywa cicho pokazuje pełny grid zamiast
         przyciętego, a to jest awaria BEZ komunikatu, więc gorsza od `KeyError`.

    PUNKT 3 PYTA OD BP-4 O TABELĘ **ORAZ O JEJ KONSUMENTÓW**. Wcześniej szukał literału
    `self._only_X` w źródle `_refresh` - a to wiązało bramkę z jednym KSZTAŁTEM kodu: enumeracja
    zeszła do `_TRIMY`, derywacja została ta sama, a bramka czerwieniała.

    ⚠ SAMO PYTANIE O WIERSZ W TABELI JEST ZA SŁABE i to jest zarzut zgodny u DWÓCH soczewek bramki
    pakietu, nie teoria: wiersz w tabeli nic nie znaczy, dopóki ktoś tabelę czyta, więc podmiana
    `trims` w `_refresh` na pustą listę przechodziłaby na zielono i produkowała dokładnie tę cichą
    awarię („perspektywa pokazuje pełny grid"), którą ten docstring nazywa gorszą od `KeyError`.
    Stąd dwa asserty o KONSUMENTACH - jeden per oś, bo osie są dwie i rozjeżdżają się osobno:
    `_refresh` przycina zbiór, `_trim_aktywny` karmi receptę powrotu.

    Punkt 3 pilnuje TRZECH miejsc naraz, bo każde z nich samo w sobie przepuszcza cichą awarię:
    ustawienia flagi w `_on_perspective`, derywacji trimu w `_refresh` i przekazania go listwie
    facetów. Czwarte miejsce - serializacja spec-a - ma własny test wyżej.

    OD G2-7d `_TRIMY` JEST JEDYNĄ ENUMERACJĄ RODZINY - i bramka pyta o to wprost (punkt 4):
    WSZYSCY konsumenci czytają tabelę, a w źródle nie ma ani jednej ręcznie wpisanej flagi
    (`self._only_…`). Dawny punkt „literał `self._only_X` jest w źródle" odwrócił znaczenie: był
    dowodem, że flaga jest gdzieś użyta, a dziś byłby dowodem powrotu drugiej listy. Klucz paska
    kryteriów składany jest z konwencji, więc kolektor literałów i18n go nie widzi - parytet
    z katalogiem trzyma punkt 5, a zachowanie całości test WYKONANIA niżej
    (`test_KAZDA_flaga_rodziny_przechodzi_caly_cykl_widoku`)."""
    import inspect
    import re
    from horreum.gui.i18n_catalog import CATALOG
    atrybuty_trimu = {atrybut for atrybut, _ in grid_mod._TRIMY}
    for nazwa, spec in grid_mod.PRESETS.items():
        assert nazwa in grid_mod._PRESET_LABELS, f"preset bez etykiety wyświetlania: {nazwa!r}"
        assert grid_mod._PRESET_LABELS[nazwa] in CATALOG, (
            f"etykieta presetu {nazwa!r} spoza katalogu i18n: {grid_mod._PRESET_LABELS[nazwa]!r}")
        for klucz in (k for k in spec if k.startswith("only_")):
            assert f"_{klucz}" in atrybuty_trimu, (
                f"flaga {klucz!r} presetu {nazwa!r} nie ma wiersza w `_TRIMY` - perspektywa "
                f"pokaże PEŁNY grid zamiast przyciętego, bez żadnego komunikatu")
    for metoda in (grid_mod.FramesView._refresh, grid_mod.FramesView._trim_aktywny,
                   grid_mod.FramesView._on_perspective, grid_mod.FramesView._save_perspective,
                   grid_mod.FramesView._describe_criteria, grid_mod.FramesView._stan_zgodny_z,
                   grid_mod.FramesView._zeruj_flagi):
        assert "_TRIMY" in inspect.getsource(metoda), (
            f"`{metoda.__name__}` przestał czytać `_TRIMY` - tabela z wierszami, których nikt nie "
            f"konsumuje, jest bramką na dane zamiast na zachowanie")
    for metoda in (grid_mod.FramesView.__init__, grid_mod.FramesView.apply_object_facet):
        assert "_zeruj_flagi" in inspect.getsource(metoda), (
            f"`{metoda.__name__}` zeruje flagi po swojemu - druga enumeracja rodziny")
    # 4. żadnej ręcznej listy: literał `self._only_…` w źródle to powrót kopii enumeracji
    reczne = re.findall(r"self\._only_\w+", _ZRODLO_GRIDU)
    assert not reczne, f"ręcznie wpisane flagi rodziny obok `_TRIMY`: {sorted(set(reczne))}"
    # 5. każda flaga ma zdanie na pasku kryteriów - klucz składany, więc kolektor i18n jest ślepy
    for atrybut, _ in grid_mod._TRIMY:
        assert grid_mod._klucz_kryterium(atrybut) in CATALOG, (
            f"flaga {atrybut!r} bez zdania na pasku kryteriów: {grid_mod._klucz_kryterium(atrybut)!r}")
    # …a tabela nie ma prawa opisywać flagi, której widok nie zna: martwy wiersz kazałby
    # `_trim_aktywny` pytać o atrybut, którego `__init__` nie stawia (AttributeError w recepcie).
    # Pytamy INSTANCJI, nie źródła: zapis `a = b = False` jest w tym pliku w użyciu (`_on_clear…`),
    # więc bramka tekstowa czerwieniałaby fałszywie przy pierwszym takim skróceniu.
    from horreum.gui import queries as queries_mod
    for atrybut, nazwa_zapytania in grid_mod._TRIMY:
        assert hasattr(grid_mod.FramesView, "_trim_aktywny")
        assert hasattr(queries_mod, nazwa_zapytania), (
            f"wiersz `_TRIMY` wskazuje nieistniejące zapytanie: {nazwa_zapytania!r}")


def test_listwa_facetow_dostaje_KOMPLET_trimow_perspektywy():
    """BRAMKA NA SIBLING-SET (bramka pakietu D-V-9a). Rodzina `only_*` rozjechała się tu po raz
    DRUGI, w miejscu, którego pierwsza bramka nie widzi: `_refresh` przycinał zbiór główny siedmioma
    setami, a listwie facetów podawał DWA (`dup_ids`, `review_ids`). Skutek był widoczny gołym okiem:
    w perspektywie „Brakujące kopie" (128 wierszy) kliknięcie wartości w listwie liczyło licznik
    facetu i godziny portfela na zbiorze BEZ przycięcia, więc listwa mówiła „NGC7000 · 60 h" obok
    siatki na trzy wiersze - UI kłamał dokładnie w chwili zawężania.

    Bramka jest STRUKTURALNA, bo defekt jest strukturalny: obie strony mają czytać JEDNĄ derywację
    (`trims`), a nie dwie listy nazwanych setów, które trzeba pamiętać, żeby zaktualizować."""
    import inspect
    zrodlo = inspect.getsource(grid_mod.FramesView._refresh)
    wywolanie = [w for w in zrodlo.splitlines() if "_reload_facet_rail(" in w]
    assert wywolanie, "nie znalazłem wywołania listwy w `_refresh`"
    assert "trims" in wywolanie[0], (
        "listwa facetów musi dostać KOMPLET trimów jedną derywacją (`trims`), nie wybrane sety - "
        f"jest: {wywolanie[0].strip()!r}")
    rail = inspect.getsource(grid_mod.FramesView._reload_facet_rail)
    assert "for trim in trims" in rail, "sibling-set musi przecinać się z KAŻDYM trimem perspektywy"
    # Wzorzec, nie sam operator: `&=` pada też w KOMENTARZU, który ostrzega przed tą pułapką,
    # a bramka łapiąca własną dokumentację nie pilnuje niczego.
    assert "sib &=" not in rail, (
        "`&=` na sibling-secie przycina MEMOIZOWANE uniwersum w miejscu (`_memo_leaf_fns`), "
        "więc kolejny facet tej samej pętli liczy na zbiorze przyciętym przez poprzednika")


def test_KAZDA_flaga_rodziny_przechodzi_caly_cykl_widoku(view, gcon, monkeypatch):
    """BRAMKA WYKONANIA na enumerację (G2-7d) - bliźniak bramki strukturalnej wyżej, bo tamta czyta
    źródło, a rozjazd tej rodziny był zawsze awarią ZACHOWANIA („Baza pusta" na pełnej bazie,
    `483df93`). Dla KAŻDEGO presetu z flagą: przełączenie stawia dokładnie jego flagę, pasek
    kryteriów ją nazywa, recepta widzi trim, zapis do bazy niesie ją pod kluczem spec-a (a resztę
    rodziny jawnie wyłączoną), a wejście z mostu planera zdejmuje wszystkie. Nowa flaga dopisana
    do `_TRIMY` wchodzi tu sama - bez dopisywania testu."""
    from PySide6.QtWidgets import QInputDialog
    from horreum.gui import i18n
    presety = [(nazwa, klucz) for nazwa, spec in grid_mod.PRESETS.items()
               for klucz in spec if klucz.startswith("only_")]
    assert len(presety) == len(grid_mod._TRIMY), "każda flaga rodziny ma dokładnie jeden preset"
    for nazwa, klucz in presety:
        view.apply_perspective(nazwa)
        wlaczone = [a for a, _ in grid_mod._TRIMY if getattr(view, a)]
        assert wlaczone == [f"_{klucz}"], f"{nazwa!r}: zapalone flagi {wlaczone}"
        assert i18n.t(f"grid.criteria.{klucz}") in view.sel_bar.criteria_label.toolTip(), nazwa
        assert view._trim_aktywny(), nazwa
        monkeypatch.setattr(QInputDialog, "getText",
                            staticmethod(lambda *a, _n=f"kopia {nazwa}", **k: (_n, True)))
        view._save_perspective()
        zapisana = dict(queries.perspectives(gcon))[f"kopia {nazwa}"]
        assert {grid_mod._klucz_spec(a): zapisana.get(grid_mod._klucz_spec(a))
                for a, _ in grid_mod._TRIMY} == {
            grid_mod._klucz_spec(a): a == f"_{klucz}" for a, _ in grid_mod._TRIMY}, nazwa
        assert grid_mod._nieznane_warunki(zapisana) == [], "spec TEGO buildu nie może ostrzegać"
        view.apply_object_facet([])
        assert not any(getattr(view, a) for a, _ in grid_mod._TRIMY), nazwa


# ═════════════════════════ G2-7d - „Wycofane, a plik wrócił" dostaje własną perspektywę


def test_wiersz_a_plik_wrocil_prowadzi_do_listy_TYLKO_swoich_klatek(view, gcon):
    """G2-7d, dowiedziony firsthandem 0811: przy populacji 2 (wycofana z plikiem + wycofana bez
    pliku) wiersz mówił „a plik wrócił 1", a klik prowadził do DWÓCH wierszy. Test idzie drogą
    człowieka - klik w wiersz Porządków, sygnał do Zbiorów - i pyta o stan widoku po nim.

    Falsyfikator: przywróć w `tasks._TASKS` cel `PRESET_RETIRED` - lista pokaże dwie klatki
    i asercja o `[wrocila]` czerwienieje."""
    from horreum.gui import rows
    wrocila = _wycofana_z_powrotem(gcon, "wroc", martwa="/stare/w.xisf", wrocily=["/nowe/w.xisf"])
    bez_pliku = _wycofana_z_powrotem(gcon, "bez", martwa="/stare/b.xisf")
    tv = tasks_mod.TasksView(gcon)
    tv.open_collection.connect(view.apply_perspective)
    try:
        tv.refresh_counts()

        def _wiersz(klucz):
            return next(tv.tasks.item(i) for i in range(tv.tasks.count())
                        if tv.tasks.item(i).data(Qt.UserRole) == klucz)

        konflikt = _wiersz("retired_conflict_frames")
        assert konflikt.data(rows.SECONDARY) == "1  ›"
        tv._on_task_clicked(konflikt)
        assert view._frame_ids == [wrocila], "lista pod klikiem liczy to samo, co liczba obok"
        assert len(view._frame_ids) == queries.tasks_state(gcon)["retired_conflict_frames"]
        assert "wycofane, a plik wrócił" in view.sel_bar.criteria_label.toolTip()
        # wiersz HISTORII dalej prowadzi do wszystkich wycofanych - to jego treść
        tv._on_task_clicked(_wiersz("retired_frames"))
        assert sorted(view._frame_ids) == sorted([wrocila, bez_pliku])
    finally:
        tv.close()


def test_dwie_wycofane_NIE_wygladaja_identycznie(view, gcon):
    """Druga połowa G2-7d: nawet na liście „Wycofane" (gdzie stoją obie) wiersz z plikiem na dysku
    musi się odróżniać. Zdanie zwykłej wycofanej („pliku już nie szukamy") jest o nim nieprawdą.
    Znacznik jest PREFIKSEM - sufiks ginie w elizji kolumny „Ścieżka" (lekcja `grid.cell.retired`)."""
    wrocila = _wycofana_z_powrotem(gcon, "wroc", martwa="/stare/w.xisf", wrocily=["/nowe/w.xisf"])
    bez_pliku = _wycofana_z_powrotem(gcon, "bez", martwa="/stare/b.xisf")
    view.apply_perspective(grid_mod.PRESET_RETIRED)

    def _tekst(fid):
        r = next(i for i, row in enumerate(view.model._rows) if row.get("frame_id") == fid)
        return view.model.data(view.model.index(r, 0), Qt.DisplayRole)

    assert _tekst(wrocila) == "(wycofana, plik wrócił)  w.xisf"
    assert _tekst(bez_pliku) == "(wycofana)  b.xisf"
    tip_wrocila, tip_bez = _path_tip(view, wrocila), _path_tip(view, bez_pliku)
    assert "znów na dysku" in tip_wrocila and "nie szukamy" not in tip_wrocila
    assert "nie szukamy" in tip_bez and "znów na dysku" not in tip_bez
    assert "2026-08-14 10:00" in tip_wrocila, "data werdyktu - jedyny jego nośnik"


def test_przywroc_w_perspektywie_konfliktu_NIE_dotyka_klatki_bez_pliku(view, gcon):
    """Pomyłka, której G2-7d miało zapobiec, nie była niewinna: „Przywróć" na zaznaczeniu listy
    cofało werdykt ręki o klatce, której pliku naprawdę nie ma. W nowej perspektywie gest na
    CAŁYM widoku trafia wyłącznie w klatkę, której przesłanka wycofania upadła."""
    wrocila = _wycofana_z_powrotem(gcon, "wroc", martwa="/stare/w.xisf", wrocily=["/nowe/w.xisf"])
    bez_pliku = _wycofana_z_powrotem(gcon, "bez", martwa="/stare/b.xisf")
    view.apply_perspective(grid_mod.PRESET_RETIRED_CONFLICT)
    _zaznacz(view, view._frame_ids)
    view._on_frame_restore()
    stan = dict(gcon.execute("SELECT id, retired_at FROM frame WHERE id IN (?, ?)",
                             (wrocila, bez_pliku)).fetchall())
    assert stan[wrocila] is None, "klatka z plikiem przywrócona"
    assert stan[bez_pliku] is not None, "werdykt o klatce bez pliku NIETKNIĘTY"
    assert queries.retired_conflict_frame_ids(gcon) == set()


# ═════════════════════════ D-V-9f - perspektywa z nowszej wersji mówi, czego nie zastosowała


def test_nieznane_warunki_liczy_tylko_to_czego_build_nie_zna():
    """Funkcja NIE zna żadnej konkretnej przyszłej flagi - pyta wyłącznie o to, czego ten build nie
    umie. Pusta wartość to nie warunek (nowsze wydanie zapisuje każdą flagę, także wyłączoną),
    a facet spoza `FACETS` pomija `compose` tak samo cicho, jak nieznany klucz `only_*`."""
    spec = {"filter": None, "columns": [], "group_by": None, "only_dups": True,
            "only_z_przyszlosci": True, "only_wylaczona": False, "sortuj_po": "date_obs",
            "facets": {"kind": {"in": [["light", "light"]]},
                       "planeta": {"in": [[1, "Mars"]]}, "pusty": {"in": [], "ex": []}}}
    assert grid_mod._nieznane_warunki(spec) == ["facets.planeta", "only_z_przyszlosci",
                                                 "sortuj_po"]
    assert grid_mod._nieznane_warunki({"filter": None, "facets": {}}) == []


def test_perspektywa_z_nowszej_wersji_MOWI_ze_pominela_warunki(view, gcon):
    """D-V-9f: spec z kluczem, którego ten build nie zna, czytał się jako „pokaż wszystko" pod
    nazwą własnej perspektywy - bez sygnału. Teraz pasek kryteriów nazywa pominięte warunki,
    a zbiór jest szerszy JAWNIE. Przejście na inną perspektywę gasi ostrzeżenie, bo przestaje ono
    dotyczyć tego, co widać.

    Falsyfikator: zdejmij człon `_nieznane_warunki` z `_describe_criteria` - pasek milczy, a liczba
    klatek (pełna baza) wygląda jak wynik perspektywy."""
    from horreum import repo
    repo.save_perspective(gcon, name="Z przyszłości", now=NOW, spec={
        "filter": None, "group_by": None, "only_z_przyszlosci": True,
        "facets": {"planeta": {"in": [[1, "Mars"]]}}})
    view._load_facets()
    view.apply_perspective("Z przyszłości")
    assert view.combo_persp.currentData() == ("saved", "Z przyszłości")
    kryteria = view.sel_bar.criteria_label.toolTip()
    assert "zapisana w nowszej wersji - 2 warunki pominięte" in kryteria, kryteria
    assert "only_z_przyszlosci" in kryteria and "facets.planeta" in kryteria
    assert view.count_label.text() == "4 klatki", "zbiór szerszy - i właśnie dlatego pasek mówi"
    view.apply_perspective(grid_mod._PRESET_CZYSTY)
    assert "nowszej wersji" not in view.sel_bar.criteria_label.toolTip()


_SPEC_Z_PRZYSZLOSCI = {"filter": None, "group_by": None, "only_z_przyszlosci": True,
                       "sortuj_po": "date_obs", "facets": {"planeta": {"in": [[1, "Mars"]]}}}


def _otworz_z_przyszlosci(view, gcon, monkeypatch, nazwa_zapisu):
    """Perspektywa nowszej wersji otwarta w tym buildzie; `QInputDialog` odpowie `nazwa_zapisu`."""
    from PySide6.QtWidgets import QInputDialog
    from horreum import repo
    repo.save_perspective(gcon, name="Z przyszłości", now=NOW, spec=_SPEC_Z_PRZYSZLOSCI)
    view._load_facets()
    view.apply_perspective("Z przyszłości")
    monkeypatch.setattr(QInputDialog, "getText",
                        staticmethod(lambda *a, **k: (nazwa_zapisu, True)))


def test_zapis_TEJ_SAMEJ_perspektywy_NIE_kasuje_warunkow_nowszej_wersji(view, gcon, monkeypatch):
    """D-V-9f, druga połowa: pasek ostrzegał, a zapis i tak gubił warunek - spec składa się ze stanu,
    a stan zna tylko to, co ten build umie. Zapis pod TĄ SAMĄ nazwą z widoku, który wciąż JEST tą
    perspektywą, scala obce klucze i facety ze świeżym stanem: poprawka człowieka (tu grupowanie)
    wchodzi, warunek nowszego wydania zostaje - i ostrzeżenie po ponownym otwarciu też.

    Falsyfikator: zdejmij `**klucze_obce` / `facety_obce` z `_save_perspective` - zapisany spec
    traci `only_z_przyszlosci` i `facets.planeta`, więc nowsze wydanie pokaże zbiór szerszy."""
    _otworz_z_przyszlosci(view, gcon, monkeypatch, "Z przyszłości")
    view.combo_group.setCurrentIndex(view.combo_group.findData("kind"))   # poprawka człowieka
    view._save_perspective()
    zapisana = dict(queries.perspectives(gcon))["Z przyszłości"]
    assert zapisana["group_by"] == "kind", "poprawka widoku weszła"
    assert zapisana["only_z_przyszlosci"] is True and zapisana["sortuj_po"] == "date_obs"
    assert zapisana["facets"]["planeta"] == {"in": [[1, "Mars"]]}
    assert grid_mod._nieznane_warunki(zapisana) == grid_mod._nieznane_warunki(_SPEC_Z_PRZYSZLOSCI)
    view.apply_perspective(grid_mod._PRESET_CZYSTY)
    view.apply_perspective("Z przyszłości")
    assert "3 warunki pominięte" in view.sel_bar.criteria_label.toolTip()


def test_zapis_pod_NOWA_nazwa_niesie_tylko_to_co_widok_zna(view, gcon, monkeypatch):
    """Druga strona reguły: nowa nazwa to nowa perspektywa TEGO buildu. Obcego warunku nikt tu nie
    widział ani nie wybrał (ten build go nie stosuje), więc nie ma prawa odziedziczyć go nowa
    perspektywa - także obcego facetu, który leży w stanie widoku po otwarciu źródła."""
    _otworz_z_przyszlosci(view, gcon, monkeypatch, "Kopia")
    view._save_perspective()
    kopia = dict(queries.perspectives(gcon))["Kopia"]
    assert grid_mod._nieznane_warunki(kopia) == []
    assert "planeta" not in kopia["facets"] and "sortuj_po" not in kopia
    zrodlo = dict(queries.perspectives(gcon))["Z przyszłości"]
    assert zrodlo == _SPEC_Z_PRZYSZLOSCI, "źródło nietknięte"


def test_zapis_z_widoku_ktory_PRZESTAL_byc_perspektywa_nie_dokleja_obcych_warunkow(
        view, gcon, monkeypatch):
    """Trzecia gałąź reguły: „× Wyczyść zbiór" zdejmuje facety, więc zbiór przestaje być tą
    perspektywą (`_stan_zgodny_z`) i etykieta odchodzi z niej. Nadpisanie starej nazwy jest wtedy
    ŚWIADOMĄ wymianą zbioru - doklejenie warunku sprzed wymiany zrobiłoby z niego trzeci, niczyj."""
    _otworz_z_przyszlosci(view, gcon, monkeypatch, "Z przyszłości")
    view._on_clear_selection()
    assert view.combo_persp.currentData() != ("saved", "Z przyszłości")
    view._save_perspective()
    zapisana = dict(queries.perspectives(gcon))["Z przyszłości"]
    assert grid_mod._nieznane_warunki(zapisana) == []


# ═════════════════════════ PACZKA B - FH-4 (pusty stan czyta receptę) · BP-5 (etykieta perspektywy)


def _pokazany(v):
    """Widok z REALNĄ widocznością. `isVisible()` niepokazanego okna jest zawsze fałszem, więc
    pytanie „czy przycisk pustego stanu widać" bez `show()` przechodziłoby niezależnie od kodu.
    Dwa obroty pętli, nie jeden - wzorzec `_pokazane()` z `test_gui_mainwindow`."""
    v.resize(1200, 800)
    v.show()
    QApplication.processEvents()
    QApplication.processEvents()
    return v


def test_BP5_wyczysc_zbior_w_Kalibracji_przestawia_etykiete_na_Przeglad(view):
    """BP-5 (bramka pakietu 0816) - hipoteza POTWIERDZONA tym testem na kodzie sprzed poprawki.
    Preset „Kalibracja" zawęża FILTREM, nie trimem (`PRESETS`), więc „× Wyczyść zbiór" zdejmuje
    właśnie jego definicję, a lista perspektyw dalej mówiła „Kalibracja" nad pełnym zbiorem.
    Etykieta idzie też w świat (`ProjectionDialog(perspektywa=combo.currentText())`).

    Grupowanie ZOSTAJE: nie należy do definicji zbioru, a lista przeskakuje bez sygnału -
    `_on_perspective` zresetowałby grupowanie i przeładował zbiór drugi raz.

    Falsyfikator: zdejmij wołanie `_etykieta_perspektywy_za_stanem` z `_refresh` → lista zostaje
    na „Kalibracji"; zdejmij `blockSignals` → grupowanie spada do „bez grupowania"."""
    view.apply_perspective("Kalibracja")
    assert view.combo_persp.currentData() == ("preset", "Kalibracja")
    assert view.combo_group.currentData() == "kind", "preset nie ustawił grupowania - układ nie powstał"
    assert view._filter_tree is not None

    view.sel_bar.btn_clear.click()
    assert view._filter_tree is None and view._facet_state == {}
    assert view.count_label.text() == "4 klatki"
    assert view.combo_persp.currentData() == ("preset", grid_mod._PRESET_CZYSTY), \
        f"etykieta kłamie o zbiorze: {view.combo_persp.currentText()!r}"
    assert view.combo_group.currentData() == "kind", "przestawienie etykiety zresetowało grupowanie"


def test_BP5_z_trimem_etykieta_trafia_w_preset_Z_TA_FLAGA_a_nie_w_Przeglad(view, monkeypatch):
    """Doprecyzowanie BP-5: dosłowne „po wyczyszczeniu zawsze Przegląd" kłamałoby od drugiej strony.
    „× Wyczyść zbiór" NIE tyka flag perspektywy (kontrakt `_on_clear_selection` - od niego zależy
    recepta powrotu), więc po geście w „Duplikatach" zbiór dalej JEST duplikatami.

    Dwie połowy: preset z trimem zostaje sobą, a ZAPISANA perspektywa z tym samym trimem i facetem
    przestaje pasować (facet zdjęty) i schodzi na preset Z TĄ FLAGĄ - jedyny, którego definicja
    zgadza się ze stanem.

    Falsyfikator: przestawiaj po wyczyszczeniu zawsze na `_PRESET_CZYSTY` → czerwienieje pierwsza
    połowa; zdejmij wołanie właściciela etykiety → druga."""
    from PySide6.QtWidgets import QInputDialog
    view.apply_perspective(grid_mod.PRESET_DUPS)
    view.facet_rail._on_item_clicked(_rail_item(view, "kind", "light"))
    view.sel_bar.btn_clear.click()
    assert view.combo_persp.currentData() == ("preset", grid_mod.PRESET_DUPS), view.combo_persp.currentText()
    assert view._only_dups and view.count_label.text() == "1 klatka"      # trim dalej przycina

    view.facet_rail._on_item_clicked(_rail_item(view, "kind", "light"))
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Duble lightów", True)))
    view._save_perspective()
    assert view.combo_persp.currentData() == ("saved", "Duble lightów")
    view.sel_bar.btn_clear.click()
    assert view.combo_persp.currentData() == ("preset", grid_mod.PRESET_DUPS), view.combo_persp.currentText()
    assert view._only_dups and view.count_label.text() == "1 klatka"


def test_BP5_zapisana_z_facetem_schodzi_na_preset_zgodny_a_bez_dopasowania_NIE_zgaduje(
        view, monkeypatch, gcon):
    """Zapisana perspektywa niesie facety w DEFINICJI (`_save_perspective`), więc „× Wyczyść zbiór"
    zdejmuje ją całą - „★ Lighty" nad pełnym zbiorem mówiłoby o widoku, którego już nie ma. Stan bez
    flag i bez filtra to definicja „Przeglądu".

    Druga połowa pinuje „nie zgaduj": perspektywa z DWIEMA flagami nie ma presetu o tej definicji
    (każdy preset niesie najwyżej jedną flagę, a `_save_perspective` bierze flagi ze stanu, więc taka
    powstaje tylko spoza GUI) - etykieta zostaje, zamiast udawać dopasowanie.

    Falsyfikator: zdejmij wołanie właściciela etykiety z `_refresh` → czerwienieje pierwsza
    połowa; przestaw przy braku dopasowania na `_PRESET_CZYSTY` → druga."""
    from PySide6.QtWidgets import QInputDialog

    from horreum import repo
    view.facet_rail._on_item_clicked(_rail_item(view, "kind", "light"))
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Lighty", True)))
    view._save_perspective()
    assert view.combo_persp.currentData() == ("saved", "Lighty")
    view.sel_bar.btn_clear.click()
    assert view.count_label.text() == "4 klatki"
    assert view.combo_persp.currentData() == ("preset", grid_mod._PRESET_CZYSTY), view.combo_persp.currentText()

    repo.save_perspective(gcon, name="Dwie flagi", now=NOW, spec={
        "filter": None, "group_by": None, "only_dups": True, "only_review": True,
        "facets": {"kind": {"in": [["light", "light"]]}}})
    view._load_facets()
    view.combo_persp.setCurrentIndex(next(i for i in range(view.combo_persp.count())
                                          if view.combo_persp.itemData(i) == ("saved", "Dwie flagi")))
    assert view._only_dups and view._only_review and view._facet_state, "perspektywa się nie nałożyła"
    view.sel_bar.btn_clear.click()
    assert view._only_dups and view._only_review                          # flagi nietknięte
    assert view.combo_persp.currentData() == ("saved", "Dwie flagi"), view.combo_persp.currentText()


def test_BP5_BLIZNIAK_most_planera_nie_zostawia_etykiety_poprzedniej_perspektywy(view, gcon):
    """Bliźniak bez ID, znaleziony przy planowaniu paczki i POTWIERDZONY tym testem przed poprawką:
    most „Pokaż klatki celu" (`apply_object_facet`) zeruje flagi i filtr - jego docstring od początku
    obiecuje powrót do perspektywy pełnej - a listę zostawiał. Z „Duplikatów" most pokazywał klatki
    celu pod etykietą „Duplikaty".

    Facet mostu NIE blokuje dopasowania do presetu: to zawężenie W RAMACH perspektywy, jak klik
    w listwie. Ta sama reguła zdejmuje po „× Wyczyść zbiór" etykietę zapisanej perspektywy.

    Falsyfikator: zdejmij wołanie właściciela etykiety z `_refresh` → lista zostaje na
    „Duplikatach"; porównuj facety dokładnie zamiast przez zawieranie → żaden preset nie pasuje
    i etykieta też zostaje."""
    gcon.execute("INSERT INTO object (id, canon, kind) VALUES (1, 'IC410', 'deep_sky')")
    gcon.execute("UPDATE frame SET object_id = 1 WHERE id IN (1, 2)")
    gcon.commit()
    view.apply_perspective(grid_mod.PRESET_DUPS)
    view.apply_object_facet([(1, "IC410")])
    assert view.count_label.text() == "2 klatki"                          # klatki celu, nie duplikaty
    assert view._facet_state == {"object": {"in": [[1, "IC410"]]}}       # facet mostu nietknięty
    assert view.combo_persp.currentData() == ("preset", grid_mod._PRESET_CZYSTY), \
        f"most pokazuje klatki celu pod cudzą etykietą: {view.combo_persp.currentText()!r}"


def test_FH4_pusty_stan_ma_warianty_a_przycisk_TYLKO_przy_recepcie(obj_view, tmp_path):
    """FH-4 (firsthand 0816, P2): pusty stan podawał receptę SPRZECZNĄ z tą, którą zdanie po geście
    podało pięć sekund wcześniej - pasek mówił „odsłoni je „× Wyczyść zbiór”", a centrum ekranu
    trwale „zmień filtr lub perspektywę". Niepusta baza bierze odtąd zdanie i gest z decyzji recepty
    (`_rodzaj_recepty_powrotu`) pytanej o klatki WIDOKU, a przycisk stoi tylko tam, gdzie jest gest:

      - perspektywa bez ani jednej klatki (pusta populacja trimu) - zdanie o perspektywie
        + przełączenie na „Przegląd";
      - zawężony zbiór - zdanie o zbiorze + „× Wyczyść zbiór", TA SAMA etykieta co na pasku zbioru
        (także w trimie, który klatki ma - osobne bramki niżej);
      - brak recepty przy niepustej bazie (dziś nieosiągalny) - uczciwe zdanie, bez obietnicy gestu;
      - pusta baza - kierunek po dostawę, bez przycisku (nie ma czego odsłaniać).

    Widżety mierzone na POKAZANYM widoku, a przy zbiorze niepustym pusty stan znika razem z przyciskiem.

    Falsyfikator: podaj pustemu stanowi przy niepustej bazie zawsze `_EMPTY_FILTER` bez przycisku
    (stan sprzed poprawki) → czerwienieją warianty trimu i zbioru."""
    from horreum.gui import i18n
    from horreum.gui.grid import FramesView
    v, _ = obj_view
    _pokazany(v)
    try:
        assert not v.empty.isVisible() and not v.empty_btn.isVisible() and v.table.isVisible()

        v.apply_perspective(grid_mod.PRESET_VANISHED)                    # baza bez zniknięć
        QApplication.processEvents()
        assert v._n_total == 0 and v.empty.isVisible() and not v.table.isVisible()
        assert v.empty.text() == i18n.t(grid_mod._EMPTY_PERSP)
        assert v.empty_btn.isVisible()
        assert v.empty_btn.text() == i18n.t("grid.empty_persp_action",
                                            perspective=i18n.t("perspective.review"))

        v.apply_perspective(grid_mod._PRESET_CZYSTY)
        v.filter_panel.filterApplied.emit({"keyword": "OBJECT", "operator": "eq", "value": "BRAK"})
        QApplication.processEvents()
        assert v._n_total == 0 and v.empty.text() == i18n.t(grid_mod._EMPTY_FILTER)
        assert v.empty_btn.isVisible() and v.empty_btn.text() == v.sel_bar.btn_clear.text()

        # Wariant dziś nieosiągalny (niepusta baza bez zawężenia pokazuje klatki) - wymuszony
        # cieniem decyzji na instancji, żeby przejść przez PRAWDZIWY `_refresh`.
        v._rodzaj_recepty_powrotu = lambda *, cel: None
        v.refresh()
        QApplication.processEvents()
        assert v.empty.isVisible() and v.empty.text() == i18n.t(grid_mod._EMPTY_VIEW)
        assert not v.empty_btn.isVisible(), "przycisk bez recepty obiecuje gest, którego nie ma"
        del v._rodzaj_recepty_powrotu

        v.apply_perspective(grid_mod._PRESET_CZYSTY)
        QApplication.processEvents()
        assert v._n_total == 4 and not v.empty.isVisible() and not v.empty_btn.isVisible()
    finally:
        v.close()

    con = db.open_db(str(tmp_path / "pusta.db"))           # QSettings izoluje już fikstura
    try:
        pusty = _pokazany(FramesView(con, now_fn=None))
        try:
            assert pusty.empty.isVisible() and pusty.empty.text() == i18n.t(grid_mod._EMPTY_DB)
            assert not pusty.empty_btn.isVisible(), "pusta baza nie ma czego odsłaniać"
        finally:
            pusty.close()
    finally:
        con.close()


def test_FH4_pusty_stan_i_pasek_podaja_TEN_SAM_gest_tam_gdzie_cele_sie_pokrywaja(obj_view):
    """JEDNA DECYZJA, DWA CELE. Pasek pyta o klatki GESTU, pusty stan o klatki WIDOKU - to dwa różne
    pytania (FH-4, poprawka po firsthandzie: w trimie, który ma klatki, odpowiedzi są różne i obie
    prawdziwe - osobne bramki niżej). Pokrywają się tam, gdzie pustkę robi to samo, co wypycha
    klatki gestu: bez trimu (zawężony zbiór) oraz w trimie o PUSTEJ populacji, także z facetem na
    wierzchu. Tam obie powierzchnie muszą wskazać JEDEN gest, a druga kopia wyboru w innej kolejności
    rozjechałaby je właśnie w układzie „oba".

    Do poprawki po firsthandzie ta bramka nazywała się „…w każdym układzie" i kodowała przesłankę,
    którą firsthand obalił: jeden gest dla obu pytań w KAŻDYM układzie zawężeń.

    Falsyfikator: zastąp w `_ustaw_pusty_stan` wołanie decyzji własnym łańcuchem
    `_zbior_zawezony()` przed `_trim_aktywny()` → układ „oba" podaje dwa różne gesty."""
    from horreum.gui import i18n
    v, _ = obj_view
    gest_dla_recepty_paska = {
        "grid.sel.out_of_view_persp": i18n.t("grid.empty_persp_action",
                                             perspective=i18n.t("perspective.review")),
        "grid.sel.out_of_view_set": i18n.t("grid.sel.clear_set"),
    }
    uklady = {
        "trim": (grid_mod.PRESET_VANISHED, {}, None),
        "zbior": (grid_mod._PRESET_CZYSTY, {}, {"keyword": "OBJECT", "operator": "eq", "value": "BRAK"}),
        "oba": (grid_mod.PRESET_VANISHED, {"kind": {"in": [["light", "light"]]}}, None),
    }
    for nazwa, (perspektywa, facety, filtr) in uklady.items():
        v.apply_perspective(perspektywa)
        v._facet_state, v._filter_tree = facety, filtr
        v.refresh()
        assert v._n_total == 0, f"{nazwa}: układ nie opróżnił widoku"
        if v._trim_aktywny():
            assert not v._populacja_trimu(), f"{nazwa}: trim ma klatki - tu cele się NIE pokrywają"
        klucz, _ = v._recepta_powrotu_do_widoku()
        assert v.empty_btn.text() == gest_dla_recepty_paska[klucz], (
            f"{nazwa}: pusty stan ({v.empty_btn.text()!r}) i pasek ({klucz}) wskazują różne gesty")


def test_FH4_przycisk_pustego_stanu_WYKONUJE_recepte_obu_rodzajow(obj_view):
    """Przycisk nie tylko cytuje receptę, ale ją WYKONUJE - bramka pytająca o sam napis przeszłaby
    także dla przycisku, po którym nic się nie odsłania (lekcja recepty paska: test klika to, co
    zdanie każe kliknąć). Oba rodzaje, bo mają różne mechanizmy celu: lista perspektyw i przycisk
    zbioru.

    Wykonawca jest JEDEN (`wykonaj_recepte_powrotu`), a CEL podaje wołający: przycisk pustego stanu
    pyta o klatki widoku, przycisk recepty paska stanu (TODO-DŁUG(FH-2e) w `app.py`) zapyta o klatki
    gestu. Klik przez `clicked` sprawdza przy okazji, że `checked: bool` nie wpada w cel.

    Falsyfikator: podepnij przycisk pod `_on_clear_selection` wprost → w perspektywie bez klatek
    klik niczego nie odsłania, bo flag perspektywy ten gest nie tyka."""
    v, _ = obj_view
    wszystkie = len(v._frame_ids)
    assert wszystkie == 4

    v.apply_perspective(grid_mod.PRESET_VANISHED)
    assert v._n_total == 0
    v.empty_btn.click()
    assert v.combo_persp.currentData() == ("preset", grid_mod._PRESET_CZYSTY)
    assert len(v._frame_ids) == wszystkie, "recepta perspektywy wykonana, a zbiór się nie odsłonił"

    v.filter_panel.filterApplied.emit({"keyword": "OBJECT", "operator": "eq", "value": "BRAK"})
    assert v._n_total == 0
    v.empty_btn.click()
    assert v._filter_tree is None and len(v._frame_ids) == wszystkie, \
        "recepta zbioru wykonana, a zbiór się nie odsłonił"


def test_FH4_firsthand_facet_gest_pusty_stan_klik_i_klatki_wracaja_ZAZNACZONE(obj_view):
    """Scenariusz z firsthandu 0816 odtworzony krok po kroku. Facet „Obiekt" zawęża widok do dwóch
    klatek, cofnięcie przypisania wypycha OBIE (nagrobek wypada z facetu, bo ten JOIN-uje po
    `f.object_id`), więc widok jest pusty. Pasek mówi „odsłoni je „× Wyczyść zbiór”" - a pusty
    stan, który zostaje na ekranie po zgaśnięciu paska, podaje TEN SAM gest, przyciskiem.

    Klik kończy drogę, nie jej połowę: klatki gestu wracają ZAZNACZONE (mechanizm `_cel_gestu`,
    FC-2), więc drugi człon recepty - „potem przywrócisz: Obiekt → …" - jest od razu wykonalny.

    Falsyfikator: podaj pustemu stanowi przy niepustej bazie zawsze `_EMPTY_FILTER` bez przycisku
    → brak gestu paska na ekranie; zdejmij odłożenie celu w `_refresh` → klatki wracają
    niezaznaczone, a kontrolka „Obiekt" stoi wygaszona."""
    from horreum.gui import i18n
    v, con = obj_view
    con.execute("INSERT INTO object(id, canon, catalog, kind) VALUES (6, 'M42', 'M', 'deep_sky')")
    con.execute("UPDATE frame SET object_id = 6 WHERE id = 3")     # facet NGC6960 = klatki 1 i 2
    con.commit()
    _pokazany(v)
    try:
        v.apply_object_facet([(5, "NGC6960")])
        assert v._n_total == 2
        _zaznacz(v, [1, 2])
        raporty, recepty = _sluchaj_paska(v)
        v._on_object_clear()
        QApplication.processEvents()

        assert v._n_total == 0, "gest nie wypchnął celu - bramka nie odtwarza firsthandu"
        assert "poza widokiem: 2" in raporty[-1], raporty[-1]
        gest = i18n.t("grid.sel.clear_set")
        assert gest in recepty[-1], recepty[-1]
        assert v.empty.isVisible() and v.empty.text() == i18n.t(grid_mod._EMPTY_FILTER), v.empty.text()
        assert v.empty_btn.isVisible() and v.empty_btn.text() == gest, v.empty_btn.text()

        v.empty_btn.click()
        QApplication.processEvents()
        assert not v.empty.isVisible() and v.table.isVisible()
        assert {r["frame_id"] for r in v._selected_data_rows()} == {1, 2}, "cel gestu zgubiony"
        assert v.sel_bar.btn_object.isEnabled(), "drugi człon recepty dalej niewykonalny"
    finally:
        v.close()


def test_FH4_pusty_stan_renderuje_EN_z_katalogu(qapp, tmp_path, monkeypatch):
    """Rollout i18n: zdania i gesty pustego stanu idą z KATALOGU. Pod EN oba warianty z receptą
    mówią po angielsku, a przycisk zbioru nosi tę samą etykietę co przycisk paska zbioru także
    w drugim języku - jedna nazwa gestu nie może się rozjechać przy tłumaczeniu.

    Falsyfikator: wpisz zdanie pustego stanu literałem zamiast przez `i18n.t` → pod EN zostaje
    polskie."""
    from PySide6.QtCore import QSettings
    monkeypatch.setattr(QSettings, "value", lambda self, k, d=None: d)
    monkeypatch.setattr(QSettings, "setValue", lambda self, k, v: None)
    from horreum.gui import i18n
    from horreum.gui.grid import FramesView
    i18n.set_lang("en")
    con = db.open_db(str(tmp_path / "en_pusty.db"))
    _seed(con)
    try:
        v = FramesView(con, now_fn=None)
        v.apply_perspective(grid_mod.PRESET_RETIRED)                     # nikt niczego nie wycofał
        assert v._n_total == 0
        assert v.empty.text() == "No frames in this perspective."
        assert v.empty_btn.text() == 'Switch to the "Review" perspective'

        v.apply_perspective(grid_mod._PRESET_CZYSTY)
        v.filter_panel.filterApplied.emit({"keyword": "OBJECT", "operator": "eq", "value": "NONE"})
        assert v._n_total == 0
        assert v.empty.text() == "No frames in this set - it is narrowed by facets or the filter."
        assert v.empty_btn.text() == "× Clear set" == v.sel_bar.btn_clear.text()
    finally:
        con.close()


def test_FH4_KAZDE_zdanie_pustego_stanu_ma_klucz_w_katalogu():
    """BRAMKA KLASY. Zdania pustego stanu idą do `i18n.t` ZMIENNĄ (stałe `_EMPTY_*`), a kolektor
    bramki i18n zbiera wyłącznie literały. Literówka w stałej renderowałaby surowy klucz - a testy
    porównujące `empty.text()` z `i18n.t(stała)` PRZESZŁYBY, bo obie strony rozwiązują ten sam
    błędny klucz na ten sam surowy napis.

    Falsyfikator: przekręć literę w którejkolwiek stałej `_EMPTY_*` → test czerwienieje."""
    from horreum.gui.i18n_catalog import CATALOG
    for stala in ("_EMPTY_DB", "_EMPTY_FILTER", "_EMPTY_PERSP", "_EMPTY_VIEW"):
        klucz = getattr(grid_mod, stala)
        assert klucz in CATALOG, f"{stala} wskazuje klucz spoza katalogu: {klucz!r}"


def _przycisk_panelu_filtra(view, klucz):
    """Przycisk panelu filtra po ETYKIECIE z katalogu - ta sama droga co klik w GUI. Panel trzyma
    „Zastosuj" i „Wyczyść" w zmiennych lokalnych konstruktora, więc szukamy ich wśród dzieci."""
    from PySide6.QtWidgets import QPushButton

    from horreum.gui import i18n
    trafione = [b for b in view.filter_panel.findChildren(QPushButton) if b.text() == i18n.t(klucz)]
    assert len(trafione) == 1, f"panel ma {len(trafione)} przycisków „{i18n.t(klucz)}”"
    return trafione[0]


def test_BP5_R1_panelowe_Wyczysc_w_Kalibracji_przestawia_etykiete_na_Przeglad(view):
    """BP-5, bliźniak INNĄ DROGĄ, potwierdzony sondą: przycisk „Wyczyść" W PANELU filtra
    nie przechodzi przez `_on_clear_selection` (`FilterPanel._clear` → `filterApplied` →
    `_on_filter`), więc po naprawie BP-5 dalej zostawiał „Kalibrację" nad pełnym zbiorem. Etykietę
    rozstrzyga odtąd właściciel na końcu `_refresh`, więc żadna droga przeładowania go nie omija.

    Klik idzie w PRAWDZIWY przycisk panelu (po etykiecie z katalogu), nie w slot: bramka wołająca
    slot przeszłaby także wtedy, gdyby przycisk był podpięty gdzie indziej. Przy okazji pinuje, że
    przełączenie perspektywy NIE wysyła sygnału panelu (`set_tree` go nie emituje) - inaczej
    właściciel etykiety działałby w środku `_on_perspective`, zanim stan jest kompletny.

    Falsyfikator: zdejmij wołanie `_etykieta_perspektywy_za_stanem` z `_refresh` → lista zostaje
    na „Kalibracji"."""
    emisje = []
    view.filter_panel.filterApplied.connect(emisje.append)
    view.apply_perspective("Kalibracja")
    assert emisje == [], "przełączenie perspektywy wysłało sygnał panelu"
    assert view.combo_group.currentData() == "kind", "preset nie ustawił grupowania - układ nie powstał"

    _przycisk_panelu_filtra(view, "grid.filter.clear").click()
    assert emisje == [None], "przycisk panelu nie poszedł drogą sygnału"
    assert view._filter_tree is None and view.count_label.text() == "4 klatki"
    assert view.combo_persp.currentData() == ("preset", grid_mod._PRESET_CZYSTY), \
        f"etykieta kłamie o zbiorze: {view.combo_persp.currentText()!r}"
    assert view.combo_group.currentData() == "kind", "przestawienie etykiety zresetowało grupowanie"


def test_BP5_R1_zmieniony_filtr_NIE_przestawia_etykiety_dopiero_zdjety_do_zera(view):
    """Granica BP-5 na drodze panelu: właściciel etykiety w `_refresh` słyszy KAŻDE „Zastosuj",
    także takie, które filtr perspektywy tylko zmienia. Zmieniony (niepusty) filtr „Kalibracji" nie
    jest definicją żadnego presetu, więc etykieta zostaje - brak dopasowania to brak zgadywania.
    Przeskok następuje dopiero wtedy, gdy filtr zejdzie do zera, bo stan jest wtedy definicją
    „Przeglądu".

    Falsyfikator: zdejmij wołanie właściciela z `_refresh` → czerwienieje druga połowa;
    przestawiaj etykietę po każdym przeładowaniu na `_PRESET_CZYSTY` → pierwsza."""
    view.apply_perspective("Kalibracja")
    view.filter_panel._rows[0]["val"].setText("light")                # „dark" → „light"
    _przycisk_panelu_filtra(view, "grid.filter.apply").click()
    assert view._filter_tree is not None
    assert view._filter_tree != grid_mod.PRESETS["Kalibracja"]["filter"], "filtr się nie zmienił - brak układu"
    assert view.combo_persp.currentData() == ("preset", "Kalibracja"), view.combo_persp.currentText()

    _przycisk_panelu_filtra(view, "grid.filter.clear").click()
    assert view.combo_persp.currentData() == ("preset", grid_mod._PRESET_CZYSTY), view.combo_persp.currentText()


def test_BP5_R1_trim_z_filtrem_panelu_zostaje_a_zapisana_schodzi_na_preset_Z_TA_FLAGA(view, monkeypatch):
    """Granica BP-5 przy trimie na drodze panelu: filtr z panelu nałożony na „Duplikaty" to zawężenie
    W RAMACH perspektywy - etykieta zostaje, a trim dalej przycina (flag `_on_filter` nie tyka). Druga
    połowa idzie tą samą drogą co bliźniak: zapisana perspektywa „duplikaty + filtr" traci filtr
    panelowym „Wyczyść" i schodzi na preset Z TĄ FLAGĄ, nie na „Przegląd".

    Falsyfikator: zdejmij wołanie właściciela z `_refresh` → druga połowa zostaje na zapisanej
    nazwie; przestawiaj etykietę po każdym przeładowaniu na `_PRESET_CZYSTY` → pierwsza gubi
    „Duplikaty"."""
    from PySide6.QtWidgets import QInputDialog
    view.apply_perspective(grid_mod.PRESET_DUPS)
    wiersz = view.filter_panel._rows[0]
    wiersz["kw"].setCurrentText("OBJECT")
    wiersz["op"].setCurrentIndex([opc for _, opc in grid_mod.OPERATORS].index("eq"))
    wiersz["val"].setText("M51")
    _przycisk_panelu_filtra(view, "grid.filter.apply").click()
    assert view._filter_tree is not None
    assert view.combo_persp.currentData() == ("preset", grid_mod.PRESET_DUPS), view.combo_persp.currentText()
    assert view._only_dups and view.count_label.text() == "1 klatka"      # bez trimu M51 = 2 klatki

    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Duble M51", True)))
    view._save_perspective()
    assert view.combo_persp.currentData() == ("saved", "Duble M51")
    _przycisk_panelu_filtra(view, "grid.filter.clear").click()
    assert view.combo_persp.currentData() == ("preset", grid_mod.PRESET_DUPS), view.combo_persp.currentText()
    assert view._only_dups and view.count_label.text() == "1 klatka"


def _przeglad_z_populacja(con):
    """Trzy lighty BEZ obiektu - populacja perspektywy „Do przeglądu" - z kartą OBJECT: dwa
    „LBN 807", jeden „M31". Karta, nie sam nagłówek, bo filtr panelu czyta `cards` (tak jak
    w firsthandzie, gdzie widok zawężał filtr OBJECT)."""
    for fid, nazwa in ((21, "LBN 807"), (22, "LBN 807"), (23, "M31")):
        con.execute("INSERT INTO frame(id, kind, filetype, sha1_data, first_seen_at) "
                    "VALUES (?, 'light', 'fits', ?, ?)", (fid, f"sha-kolejka{fid}", NOW))
        con.execute("INSERT INTO header(frame_id, raw_json, object_raw) VALUES (?, '{}', ?)",
                    (fid, nazwa))
        con.execute("INSERT INTO cards(frame_id, keyword, idx, value_raw, value_num, value_type) "
                    "VALUES (?, 'OBJECT', 0, ?, NULL, 'str')", (fid, nazwa))
        con.execute("INSERT INTO location(frame_id, volume, path, present) VALUES (?, 'V', ?, 1)",
                    (fid, rf"R:\ASTRO_\LIGHTS\KOLEJKA\k{fid}.fits"))
    con.commit()
    return [21, 22, 23]


def test_FH4_pusty_stan_w_trimie_Z_KLATKAMI_zdejmuje_zbior_i_zostawia_perspektywe(obj_view):
    """FH-4, poprawka po firsthandzie (blokada P1, regresja wobec `89ed8bf`). „Do przeglądu" MA
    klatki, a filtr opróżnia widok - pustkę robi ZBIÓR, nie perspektywa. Pusty stan mówił „Brak
    klatek w tej perspektywie" i prowadził na „Przegląd", czyli wyrzucał z kolejki na całe archiwum
    (zmierzone na kopii żywej bazy: 16 901 klatek, a w kolejce czekało 8; powrót kosztował trzy
    interakcje zamiast jednej). Recepta WIDOKU to „× Wyczyść zbiór": perspektywa zostaje, jej
    klatki wracają.

    Falsyfikator: pomiń w `_rodzaj_recepty_powrotu` gałąź celu „widok" (trim wygrywa zawsze) →
    pusty stan wraca do zdania o perspektywie i przejścia na „Przegląd"."""
    from horreum.gui import i18n
    v, con = obj_view
    kolejka = _przeglad_z_populacja(con)
    v.apply_perspective("Do przeglądu")
    assert sorted(v._frame_ids) == kolejka, "fikstura nie zbudowała kolejki - brak układu"
    v.filter_panel.filterApplied.emit({"keyword": "OBJECT", "operator": "eq", "value": "BRAK"})
    assert v._n_total == 0
    assert v.empty.text() == i18n.t(grid_mod._EMPTY_FILTER), v.empty.text()
    assert v.empty_btn.text() == i18n.t("grid.sel.clear_set"), v.empty_btn.text()

    v.empty_btn.click()
    assert v.combo_persp.currentData() == ("preset", "Do przeglądu"), v.combo_persp.currentText()
    assert v._only_review and v._filter_tree is None
    assert sorted(v._frame_ids) == kolejka, "kolejka nie wróciła po recepcie widoku"


def test_FH4_po_GESCIE_w_trimie_z_klatkami_pasek_i_pusty_stan_podaja_rozne_PRAWDZIWE_gesty(obj_view):
    """Układ z firsthandu po REALNYM geście: „Do przeglądu" (3) → filtr OBJECT = LBN 807 (2) →
    przypisanie obiektu. Nadane klatki wypadają z trimu (kolejka to klatki BEZ obiektu), więc widok
    jest pusty, a w kolejce czeka trzecia.

    Pasek i pusty stan odpowiadają na DWA pytania i obie odpowiedzi są prawdziwe: pasek mówi
    o klatkach GESTU - te są już tylko w „Przeglądzie"; pusty stan mówi o klatkach WIDOKU - kolejka
    ma jeszcze robotę, więc „× Wyczyść zbiór" ją oddaje i perspektywy nie rusza. Test WYKONUJE obie
    recepty (pustego stanu przyciskiem, paska wykonawcą z celem „gest" - drogą, którą pójdzie
    FH-2e), bo bramka pytająca o sam napis przepuściłaby receptę, po której nic się nie odsłania.

    Falsyfikator: pomiń gałąź celu „widok" → pusty stan znów wyrzuca z kolejki; każ celowi „gest"
    też pytać o populację → pasek obiecuje „× Wyczyść zbiór", po którym klatki gestu nie wracają."""
    from horreum.gui import i18n
    v, con = obj_view
    _przeglad_z_populacja(con)
    v.apply_perspective("Do przeglądu")
    v.filter_panel.filterApplied.emit({"keyword": "OBJECT", "operator": "eq", "value": "LBN 807"})
    assert sorted(v._frame_ids) == [21, 22], "filtr nie zawęził kolejki - brak układu"
    _zaznacz(v, [21, 22])
    raporty, recepty = _sluchaj_paska(v)
    v._on_object_recent("LBN807", "LBN", "deep_sky")

    assert v._n_total == 0, "gest nie wypchnął celu z kolejki - brak układu"
    assert "poza widokiem: 2" in raporty[-1], raporty[-1]
    assert i18n.t("grid.sel.out_of_view_persp", perspective=i18n.t("perspective.review")) \
        in recepty[-1], recepty[-1]
    assert v.empty.text() == i18n.t(grid_mod._EMPTY_FILTER), v.empty.text()
    assert v.empty_btn.text() == i18n.t("grid.sel.clear_set"), v.empty_btn.text()

    v.empty_btn.click()                                              # recepta WIDOKU
    assert v.combo_persp.currentData() == ("preset", "Do przeglądu")
    assert v._frame_ids == [23], "reszta kolejki nie wróciła"

    v.wykonaj_recepte_powrotu(cel=grid_mod._CEL_GEST)                # recepta GESTU (droga FH-2e)
    assert v.combo_persp.currentData() == ("preset", grid_mod._PRESET_CZYSTY)
    assert {21, 22} <= set(v._frame_ids), "recepta paska wykonana, a klatki gestu się nie odsłoniły"


def test_FH4_wariant_pustego_stanu_idzie_za_POPULACJA_trimu_a_nie_za_samym_trimem(obj_view):
    """Granica poprawki po firsthandzie. Pustkę robi PERSPEKTYWA, gdy jej populacja jest pusta -
    wtedy „× Wyczyść zbiór" niczego by nie odsłonił i jedynym gestem jest przejście na „Przegląd",
    choć facet też zawęża. Ta sama perspektywa z tym samym facetem przechodzi na wariant zbioru,
    gdy tylko populacja przestaje być pusta: wariant idzie za PRZYCZYNĄ pustki, nie za samą
    obecnością trimu.

    Falsyfikator: wybieraj wariant zbioru przy każdym zawężeniu zbioru, bez pytania o populację →
    pierwsza połowa podaje przycisk, po którym nic się nie odsłania; pomiń gałąź celu „widok" →
    druga połowa zostaje przy perspektywie."""
    from horreum.gui import i18n
    v, con = obj_view
    lighty = {"kind": {"in": [["light", "light"]]}}
    v.apply_perspective(grid_mod.PRESET_VANISHED)                    # nic jeszcze nie zniknęło
    v._facet_state = lighty
    v.refresh()
    assert v._n_total == 0
    assert v.empty.text() == i18n.t(grid_mod._EMPTY_PERSP), v.empty.text()
    assert v.empty_btn.text() == i18n.t("grid.empty_persp_action",
                                        perspective=i18n.t("perspective.review"))
    v.empty_btn.click()
    assert v.combo_persp.currentData() == ("preset", grid_mod._PRESET_CZYSTY) and v._n_total == 4

    con.execute("UPDATE location SET present = 0 WHERE frame_id = 4")  # dark znika z dysku
    con.commit()
    v.apply_perspective(grid_mod.PRESET_VANISHED)
    v._facet_state = lighty                                           # facet wyklucza zniknięty dark
    v.refresh()
    assert v._n_total == 0
    assert v.empty.text() == i18n.t(grid_mod._EMPTY_FILTER), v.empty.text()
    assert v.empty_btn.text() == i18n.t("grid.sel.clear_set"), v.empty_btn.text()
    v.empty_btn.click()
    assert v.combo_persp.currentData() == ("preset", grid_mod.PRESET_VANISHED)
    assert v._frame_ids == [4], "zniknięta klatka perspektywy nie wróciła"


def test_BP5_klik_w_listwie_zdejmujacy_facet_definicji_przestawia_etykiete_zapisanej(obj_view, monkeypatch):
    """BP-5 domknięty w `_refresh`: zapisana perspektywa zdefiniowana facetem („★ Lighty" =
    `kind in light`) po jednym kliknięciu `✓ light` (in → ex) pokazywała DOPEŁNIENIE swojej definicji
    pod swoją nazwą, a `ProjectionDialog` bierze tę nazwę do manifestu. Klik w listwie
    (`_on_facet_change`) nie wołał właściciela etykiety - od tej zmiany woła go KAŻDE przeładowanie
    zbioru, więc żadna droga go nie omija.

    Granice, obie z reguły zawierania facetów: klik w INNEJ grupie dokłada zawężenie w ramach
    „★ Lighty" (jej facet dalej stoi), a klik facetu pod presetem nie ma czego przestawiać.

    Falsyfikator: zdejmij wołanie właściciela z `_refresh` → etykieta zostaje na „★ Lighty" nad
    dopełnieniem jej definicji."""
    from PySide6.QtWidgets import QInputDialog
    v, _ = obj_view
    v.facet_rail._on_item_clicked(_rail_item(v, "kind", "light"))
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Lighty", True)))
    v._save_perspective()
    assert v.combo_persp.currentData() == ("saved", "Lighty")

    v.facet_rail._on_item_clicked(_rail_item(v, "object", 5))       # INNA grupa: zawężenie w ramach
    assert "object" in v._facet_state
    assert v.combo_persp.currentData() == ("saved", "Lighty"), v.combo_persp.currentText()

    v.facet_rail._on_item_clicked(_rail_item(v, "kind", "light"))   # ✓ light: in → ex
    assert v._facet_state["kind"] == {"ex": [["light", "light"]]}
    assert v.combo_persp.currentData() == ("preset", grid_mod._PRESET_CZYSTY), \
        f"dopełnienie definicji pod jej nazwą: {v.combo_persp.currentText()!r}"

    v.facet_rail._on_item_clicked(_rail_item(v, "kind", "light"))   # pod presetem: ex → brak
    assert "kind" not in v._facet_state
    assert v.combo_persp.currentData() == ("preset", grid_mod._PRESET_CZYSTY)


def test_BP5_BLIZNIAK_odbudowa_listy_perspektyw_zostawia_BIEZACA_pozycje(view, monkeypatch):
    """Bliźniak BP-5 w `_load_facets`: odbudowa listy perspektyw pod `blockSignals` zostawiała indeks
    0, a po etapie Dostawy gospodarz woła właśnie `_load_facets()` + `refresh()`
    (`app._on_stage_finished`). Combo mówiło wtedy „Przegląd" nad zbiorem z trimem - a pusty stan
    potrafił pod nim proponować przejście na „Przegląd". Pozycja wraca PO DANYCH, także zapisana:
    jej nazwy nie da się odtworzyć ze stanu, bo właściciel etykiety zna tylko presety.

    Falsyfikator: zdejmij odtwarzanie pozycji w `_load_facets` → „Duplikaty" ratuje jeszcze
    właściciel w `_refresh`, ale zapisana perspektywa spada na preset."""
    from PySide6.QtWidgets import QInputDialog
    view.apply_perspective(grid_mod.PRESET_DUPS)
    view._load_facets()
    view.refresh()
    assert view.combo_persp.currentData() == ("preset", grid_mod.PRESET_DUPS), view.combo_persp.currentText()
    assert view._only_dups and view.count_label.text() == "1 klatka"

    view.apply_perspective(grid_mod._PRESET_CZYSTY)
    view.facet_rail._on_item_clicked(_rail_item(view, "kind", "light"))
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Lighty", True)))
    view._save_perspective()
    view._load_facets()
    view.refresh()
    assert view.combo_persp.currentData() == ("saved", "Lighty"), view.combo_persp.currentText()


def test_zdanie_pominiec_JEDEN_dom_czlonow_zdania_osi_obiektu():
    """R-S2b-13: `zdanie_pominiec` jest jedynym domem pętli rozbicia dla trzech powierzchni osi
    obiektu (gesty Zbiorów, zatwierdzanie ze ścieżki, nadanie z kolejki). Pytamy o cztery rzeczy:
    KAŻDY człon rozbicia w kolejności `skipped_breakdown`, czasownik członu „nothing" z GESTU
    (FC-6), „w tym gotowy obraz" POZA pętlą pominięć i na jej końcu (D-OW-7) oraz ciszę przy
    zerze - gest bez pominięć nie dostaje ani separatora, ani pustego członu.

    Falsyfikator: zdejmij człon `stacks` z helpera → pierwsza asercja; zignoruj `nothing_key`
    przy wyborze klucza → druga; zdejmij warunek `if n` z pętli → trzecia (człony „: 0")."""
    from horreum import repo
    g = repo.ObjectGesture(assigned=3, skipped_kind=1, skipped_source=2, skipped_nothing=3,
                           skipped_no_memory=4, skipped_drift=5, stacks=1)
    assert grid_mod.zdanie_pominiec(g) == (
        " · kalibracja: 1 · z nagłówka/regionu: 2 · nie było czego cofać: 3"
        " · bez zapamiętanego obiektu: 4 · zmieniły się w międzyczasie: 5"
        " · w tym gotowy obraz: 1")
    przywracanie = grid_mod.zdanie_pominiec(
        g, nothing_key="grid.sel.object_restore_skip_nothing")
    assert "· nie było czego przywrócić: 3" in przywracanie and "cofać" not in przywracanie
    assert grid_mod.zdanie_pominiec(repo.ObjectGesture(assigned=7)) == ""
