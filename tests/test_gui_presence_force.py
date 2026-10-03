"""Dostawa: zapis zniknięć ponad progiem hamulca przez dialog z liczbą POTWIERDZONĄ (AR-31 (6)).

Przebiegi idą w prawdziwym `QThread` (jak `test_gui_pipeline.py`), a dialog prowadzi prawdziwe
kliknięcie w modal (`QApplication.activeModalWidget`). Kontrakt: dialog tylko przy hamulcu
progowym, domyślnie „Anuluj”; „Anuluj” = zero zapisu, zatwierdzenie = droga `force`; przy
pustym drzewie ani sekcji zapisu, ani dialogu."""
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

pytest.importorskip("PySide6")

from astropy.io import fits

from horreum import db, presence
from horreum.gui import i18n
from horreum.gui.pipeline import PipelineView

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

NOW = "2026-10-03T15:00:00"


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


def _tree(tmp_path, n):
    t = tmp_path / "t"
    t.mkdir()
    for i in range(n):
        hdu = fits.PrimaryHDU(data=np.full((4, 4), i + 1, np.uint16))
        hdu.header["INSTRUME"] = "ZWO ASI2600MM Pro"
        hdu.header["IMAGETYP"] = "LIGHT"
        fits.HDUList([hdu]).writeto(str(t / f"l{i}.fits"))
    return str(t)


def _czekaj(view, timeout_ms=20000):
    loop = QEventLoop()
    view.running_changed.connect(lambda r: loop.quit() if r is False else None)
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()


def _absent(db_path):
    con = db.open_db(db_path)
    try:
        return con.execute("SELECT COUNT(*) FROM location WHERE present = 0").fetchone()[0]
    finally:
        con.close()


def _view_po_skanie(tmp_path, n):
    db_path = str(tmp_path / "p.db")
    db.open_db(db_path).close()
    root = _tree(tmp_path, n)
    view = PipelineView(db_path, now_fn=lambda: NOW)
    view._root = root
    view._on_scan()
    _czekaj(view)
    return view, db_path, root


def _klik_w_modal(wybor, zapis):
    """Kliknij w otwarty `QMessageBox` (powtarza, aż modal się pojawi). `wybor` = "ok"/"cancel";
    `zapis` dostaje tekst, przycisk domyślny i etykiety przycisków - dowód z ekranu."""
    def proba():
        box = QApplication.activeModalWidget()
        if not isinstance(box, QMessageBox):
            QTimer.singleShot(20, proba)
            return
        przyciski = box.buttons()
        cancel = box.defaultButton()
        zapis.update(text=box.text(), default=cancel.text(),
                     labels=[b.text() for b in przyciski], escape=box.escapeButton() is cancel)
        cel = cancel if wybor == "cancel" else next(b for b in przyciski if b is not cancel)
        cel.click()
    QTimer.singleShot(0, proba)


def test_dialog_przy_hamulcu_anuluj_bez_zapisu_ok_zapisuje_force(qapp, tmp_path, monkeypatch):
    i18n.set_lang("pl")
    monkeypatch.setattr(presence, "_BRAKE_MIN", 1)        # 2 zniknięcia z 4 = ponad progiem
    view, db_path, root = _view_po_skanie(tmp_path, 4)
    for n in ("l0.fits", "l1.fits"):
        os.remove(str(Path(root) / n))

    view._on_presence()                                   # DRY z liczeniem pod hamulcem
    _czekaj(view)
    assert not view.box_vanished.isHidden() and not view.btn_mark_vanished.isHidden()
    assert view.lbl_vanished.text().startswith("Zniknęły 2 kopie")
    assert view._presence_params["force"] == 2

    zapis = {}
    _klik_w_modal("cancel", zapis)
    view._on_mark_vanished()
    assert view._thread is None and _absent(db_path) == 0          # Anuluj = zero zapisu
    assert zapis["default"] == "Anuluj" and zapis["escape"]
    assert "zniknęły 2 kopie" in zapis["text"] and "(1)" in zapis["text"]
    assert "Oznacz 2 kopie" in zapis["labels"]
    assert not view.btn_mark_vanished.isHidden()                   # decyzja dalej do podjęcia

    _klik_w_modal("ok", zapis)
    view._on_mark_vanished()
    _czekaj(view)
    assert _absent(db_path) == 2
    assert view.lbl_vanished.text().startswith("Oznaczono 2 kopie")


def test_ponizej_progu_zapis_bez_dialogu(qapp, tmp_path, monkeypatch):
    view, db_path, root = _view_po_skanie(tmp_path, 3)
    os.remove(str(Path(root) / "l0.fits"))
    view._on_presence()
    _czekaj(view)
    assert "force" not in view._presence_params
    pytania = []
    monkeypatch.setattr(view, "_ask_force", lambda *a: pytania.append(a) or False)
    view._on_mark_vanished()
    _czekaj(view)
    assert pytania == [] and _absent(db_path) == 1


def test_drzewo_puste_bez_sekcji_i_bez_dialogu(qapp, tmp_path, monkeypatch):
    view, db_path, root = _view_po_skanie(tmp_path, 3)
    for n in ("l0.fits", "l1.fits", "l2.fits"):
        os.remove(str(Path(root) / n))
    view._on_presence()
    _czekaj(view)
    assert view.box_vanished.isHidden() and view._presence_params is None
    assert "drzewo puste" in view.lbl_summary.text()
    pytania = []
    monkeypatch.setattr(view, "_ask_force", lambda *a: pytania.append(a) or True)
    view._on_mark_vanished()
    assert pytania == [] and view._thread is None and _absent(db_path) == 0


def test_zlota_akcja_nie_liczy_pod_hamulcem(qapp, tmp_path, monkeypatch):
    """DRY w „Przetwórz wszystko” nie niesie flagi: pod hamulcem dalej bez kosztu `stat`."""
    monkeypatch.setattr(presence, "_BRAKE_MIN", 1)
    view, db_path, root = _view_po_skanie(tmp_path, 4)
    for n in ("l0.fits", "l1.fits"):
        os.remove(str(Path(root) / n))
    view._on_all()
    _czekaj(view, timeout_ms=40000)
    assert view.box_vanished.isHidden() and view._presence_params is None
    assert _absent(db_path) == 0


def _pod_hamulcem(qapp, tmp_path, monkeypatch):
    """Widok po DRY pod hamulcem progowym: 2 zniknięcia z 4, dialog do zatwierdzenia."""
    i18n.set_lang("pl")
    monkeypatch.setattr(presence, "_BRAKE_MIN", 1)
    view, db_path, root = _view_po_skanie(tmp_path, 4)
    for n in ("l0.fits", "l1.fits"):
        os.remove(str(Path(root) / n))
    view._on_presence()
    _czekaj(view)
    return view, db_path, root


def test_dialog_zamraza_zbior_a_inny_zbior_przy_zapisie_nic_nie_zapisuje(qapp, tmp_path,
                                                                        monkeypatch):
    """Z4: dialog obiecuje TE kopie, które user widział. Między sprawdzeniem a kliknięciem jedna
    wraca, druga znika - liczba ta sama, zapis zero i raport mówi dlaczego.
    Falsyfikator: zdejmij `expected_gone_ids` z zamrożonych parametrów → oznaczone 2 kopie."""
    view, db_path, root = _pod_hamulcem(qapp, tmp_path, monkeypatch)
    con = db.open_db(db_path)
    ids = tuple(sorted(r[0] for r in con.execute(
        "SELECT id FROM location WHERE path LIKE '%l0.fits' OR path LIKE '%l1.fits'")))
    con.close()
    assert view._presence_params["expected_gone_ids"] == ids
    hdu = fits.PrimaryHDU(data=np.full((4, 4), 1, np.uint16))
    hdu.header["INSTRUME"] = "ZWO ASI2600MM Pro"
    hdu.header["IMAGETYP"] = "LIGHT"
    fits.HDUList([hdu]).writeto(str(Path(root) / "l0.fits"))      # wróciła
    os.remove(str(Path(root) / "l2.fits"))                          # zniknęła inna
    monkeypatch.setattr(view, "_ask_force", lambda *a: True)
    view._on_mark_vanished()
    _czekaj(view)
    assert _absent(db_path) == 0
    assert "zbiór potwierdzonych zniknięć inny" in view.lbl_summary.text()


def test_dialog_info_obiecuje_zbior_nie_liczbe():
    i18n.set_lang("pl")
    assert "dokładnie tyle" not in i18n.t("pipeline.force.info")
    assert "inne kopie" in i18n.t("pipeline.force.info")


def test_odmowa_po_dialogu_mowi_powod_na_pasku(qapp, tmp_path, monkeypatch):
    """Z5: w trakcie modala ruszył zapis nagłówków albo wynik przepadł - klik „Oznacz” nie może
    zniknąć bez słowa. Falsyfikator: wróć do gołego `return` po dialogu → `statusy == []`."""
    view, db_path, root = _pod_hamulcem(qapp, tmp_path, monkeypatch)
    statusy = []
    view.status_message.connect(statusy.append)

    def _zapis_w_trakcie(*_a):
        view._writeback_busy = True
        return True
    monkeypatch.setattr(view, "_ask_force", _zapis_w_trakcie)
    view._on_mark_vanished()
    assert statusy == [i18n.t("pipeline.refuse.writeback")]
    assert view._thread is None and view._presence_params is not None and _absent(db_path) == 0

    view._writeback_busy = False
    statusy.clear()

    def _wynik_przepadl(*_a):
        view._forget_vanished()
        return True
    monkeypatch.setattr(view, "_ask_force", _wynik_przepadl)
    view._on_mark_vanished()
    assert statusy == [i18n.t("pipeline.refuse.mark_stale")]
    assert view._thread is None and _absent(db_path) == 0


@pytest.mark.parametrize("n, pl, pl_ok, en, en_ok", [
    (1, "zniknęła 1 kopia", "Oznacz 1 kopię", "1 copy is gone", "Mark 1 copy"),
    (2, "zniknęły 2 kopie", "Oznacz 2 kopie", "2 copies are gone", "Mark 2 copies"),
    (5, "zniknęło 5 kopii", "Oznacz 5 kopii", "5 copies are gone", "Mark 5 copies"),
    (12, "zniknęło 12 kopii", "Oznacz 12 kopii", "12 copies are gone", "Mark 12 copies"),
    (22, "zniknęły 22 kopie", "Oznacz 22 kopie", "22 copies are gone", "Mark 22 copies"),
])
def test_odmiana_dialogu(n, pl, pl_ok, en, en_ok):
    try:
        i18n.set_lang("pl")
        assert pl in i18n.t_plural("pipeline.force.text", n, limit=50)
        assert i18n.t_plural("pipeline.force.ok", n) == pl_ok
        i18n.set_lang("en")
        assert en in i18n.t_plural("pipeline.force.text", n, limit=50)
        assert i18n.t_plural("pipeline.force.ok", n) == en_ok
    finally:
        i18n.set_lang("pl")
