"""Dialog projekcji (KROK 6, warstwa widżetów) — testy STERUJĄCE realnym oknem Qt (offscreen).
DRY podgląd (raport, zero mutacji), guard §0 (korzeń bez wykluczenia → „Utwórz" zablokowane),
układ wbpp-feed, „Utwórz…" na PRAWDZIWYCH plikach (hardlink pod korzeniem wykluczonym), pusta
perspektywa w FramesView. `importorskip` — bez PySide6 plik pomijany. Realny R: NIGDY nie dotykany."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from horreum import db, projection

from PySide6.QtWidgets import QApplication

from horreum.gui.projection_dialog import ProjectionDialog

NOW = "2026-07-04T00:00:00+00:00"


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


def _seed_files(con, tmp_path, n=2):
    """`n` frame'ów z PRAWDZIWYMI plikami (do os.link w „Utwórz"). Bez header/object/filter → segmenty
    _UNSET (test plumbingu dialogu). Zwraca listę frame_id."""
    lib = tmp_path / "lib"
    lib.mkdir()
    for i in range(n):
        p = lib / f"raw{i}.fits"
        p.write_bytes(b"DATA" + bytes([i]))
        con.execute("INSERT INTO frame (id, sha1_data, kind, filetype, first_seen_at) VALUES (?,?,?,?,?)",
                    (i + 1, f"d{i}", "light", "fits", NOW))
        con.execute("INSERT INTO location (frame_id, volume, path, present) VALUES (?,?,?,?)",
                    (i + 1, "V", str(p), 1))
    con.commit()
    return [i + 1 for i in range(n)]


def test_dialog_dry_i_utworz(qapp, tmp_path):
    con = db.open_db(str(tmp_path / "g.db"))
    ids = _seed_files(con, tmp_path, 2)
    dlg = ProjectionDialog(con, ids, now_fn=lambda: NOW)
    assert dlg.btn_dry.isDefault()                        # akcja główna = przycisk domyślny (wizytator #1)
    root = tmp_path / "_WBPP" / "feed"
    dlg.edit_root.setText(str(root))
    dlg._on_dry()
    assert "do zlinkowania: 2" in dlg.report.toPlainText()
    assert dlg.btn_apply.isEnabled()
    assert not root.exists()                              # DRY: zero tworzenia
    dlg._on_apply()
    assert "zlinkowano: 2" in dlg.report.toPlainText()
    linked = list((root / "_UNSET" / "_UNSET").glob("*.fits"))
    assert len(linked) == 2
    for lf in linked:                                     # prawdziwy hardlink
        src = tmp_path / "lib" / lf.name
        assert os.stat(str(src)).st_ino == os.stat(str(lf)).st_ino
    assert (root / projection.MANIFEST_NAME).exists()
    assert not dlg.btn_apply.isEnabled()                  # po Utwórz → wymaga nowego DRY
    con.close()


def test_dialog_guard_zly_korzen(qapp, tmp_path):
    con = db.open_db(str(tmp_path / "g2.db"))
    ids = _seed_files(con, tmp_path, 1)
    dlg = ProjectionDialog(con, ids, now_fn=lambda: NOW)
    dlg.edit_root.setText(str(tmp_path / "LIGHTS"))       # brak segmentu wykluczonego
    dlg._on_dry()
    assert "wykluczonego" in dlg.report.toPlainText()
    assert not dlg.btn_apply.isEnabled()                  # guard → „Utwórz" zablokowane
    con.close()


def test_dialog_zmiana_parametru_unieważnia_apply(qapp, tmp_path):
    """Po udanym DRY zmiana korzenia/układu unieważnia „Utwórz" (świeży DRY pod nowe parametry)."""
    con = db.open_db(str(tmp_path / "g3.db"))
    ids = _seed_files(con, tmp_path, 1)
    dlg = ProjectionDialog(con, ids, now_fn=lambda: NOW)
    dlg.edit_root.setText(str(tmp_path / "_WBPP" / "a"))
    dlg._on_dry()
    assert dlg.btn_apply.isEnabled()
    dlg.combo_layout.setCurrentIndex(1)                   # zmiana układu → invalidate
    assert not dlg.btn_apply.isEnabled()
    con.close()


def test_dialog_layout_wbpp_feed(qapp, tmp_path):
    con = db.open_db(str(tmp_path / "g4.db"))
    ids = _seed_files(con, tmp_path, 1)
    dlg = ProjectionDialog(con, ids, now_fn=lambda: NOW)
    dlg.combo_layout.setCurrentIndex(1)                   # wbpp-feed (3 segmenty)
    dlg.edit_root.setText(str(tmp_path / "_Review" / "x"))
    dlg._on_dry()
    assert "do zlinkowania: 1" in dlg.report.toPlainText()
    con.close()


def test_framesview_projekcja_pusta_perspektywa(qapp, tmp_path):
    """FramesView._open_projection na pustym gridzie → szczery status, bez dialogu (bez exec/blokady)."""
    from horreum.gui.grid import FramesView

    con = db.open_db(str(tmp_path / "fv.db"))
    view = FramesView(con, now_fn=lambda: NOW)
    msgs = []
    view.status_message.connect(msgs.append)
    view._frame_ids = []
    view._open_projection()
    assert any("brak widocznych" in m for m in msgs)
    con.close()
