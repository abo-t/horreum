"""Widok „Klatki" (PLAN_gui_grid) — testy STERUJĄCE realnym oknem Qt (offscreen). Model 3 stanów +
sort + grupowanie; FilterPanel → drzewo; FramesView refresh/filtr/perspektywa. `importorskip` na poziomie
modułu (§9.4): bez PySide6 plik się POMIJA (pełny pytest bez Qt zostaje prawdziwy)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from horreum import db, pivot as pivot_mod
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


def test_view_perspektywa_duplikaty(view):
    idx = view.combo_persp.findText("Duplikaty")
    view.combo_persp.setCurrentIndex(idx)
    assert view.count_label.text() == "1 klatek"  # tylko f1 (n_present=2)


def test_view_grupowanie(view):
    idx = view.combo_group.findData("kind")
    view.combo_group.setCurrentIndex(idx)
    groups = [r for r in view.model._rows if "_group" in r]
    assert {g["_group"] for g in groups} == {"light", "master_flat"}


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
