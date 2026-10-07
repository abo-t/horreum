"""„Wskaż katalog…" (tryb zaawansowany) nie dotyka dysku w wątku okna (AR-44) + sprzątanie widgetów
po testach GUI (BP-7). `importorskip` na poziomie modułu: bez PySide6 plik się POMIJA."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEventLoop, QThread, QTimer
from PySide6.QtWidgets import QApplication, QFileDialog, QWidget

from horreum import db
from horreum.gui import i18n
from horreum.gui.pipeline import PipelineView

NOW = "2026-07-03T14:00:00"


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


def _czekaj_na_koniec(view, timeout_ms=20000):
    """Kręci pętlę do końca etapu w tle (`running_changed(False)`); wątek już zakończony → wraca."""
    if view._thread is None:
        return
    loop = QEventLoop()
    view.running_changed.connect(lambda r: loop.quit() if r is False else None)
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()


def _widok(tmp_path, monkeypatch, katalog):
    db_path = str(tmp_path / "p.db")
    db.open_db(db_path).close()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory",
                        staticmethod(lambda *a, **k: str(katalog)))
    return PipelineView(db_path, now_fn=lambda: NOW)


def test_wskaz_katalog_mierzy_serial_w_watku_tla(qapp, tmp_path, monkeypatch, ustawienia):
    """AR-44: serial woluminu na etykiecie mierzy sonda wątku tła (`PipelineWorker._zrodlo`), nie
    slot okna; po zakończeniu etykiety mówią to samo co przy pomiarze w oknie.

    Falsyfikator: przywróć `volume_serial(path)` w `_set_root` → pomiar biegnie w wątku okna."""
    import horreum.gui.pipeline as pl
    kat = tmp_path / "t"
    kat.mkdir()
    watki = []

    def _serial(path):
        watki.append(QThread.currentThread())
        return "DEADBEEF"

    monkeypatch.setattr(pl, "volume_serial", _serial)
    view = _widok(tmp_path, monkeypatch, kat)
    try:
        glowny = view.thread()
        view._on_pick_dir()
        _czekaj_na_koniec(view)
        assert watki, "sonda serialu nie biegła wcale"
        assert all(w is not glowny for w in watki), "serial zmierzony w wątku okna"
        assert view._root == str(kat) and view.lbl_root.text() == str(kat)
        assert view.lbl_volume.text() == i18n.t("pipeline.volume_ok", serial="DEADBEEF")
        assert view._thread is None and view.btn_scan.isEnabled()
    finally:
        view.close()


def test_wskaz_katalog_nieustalony_serial_i_katalog_ktory_odpadl(qapp, tmp_path, monkeypatch,
                                                                 ustawienia):
    """Serial nieustalony (`None`) i katalog, który odpadł po wyborze z dialogu, zostają wskazanym
    źródłem z neutralną etykietą - jak dawny pomiar w oknie; zero wyjątku i zero wiszącego wątku."""
    import horreum.gui.pipeline as pl
    monkeypatch.setattr(pl, "volume_serial", lambda path: None)
    istniejacy = tmp_path / "t"
    istniejacy.mkdir()
    brak = tmp_path / "nie_ma_takiego"
    for kat in (istniejacy, brak):
        view = _widok(tmp_path, monkeypatch, kat)
        try:
            view._on_pick_dir()
            _czekaj_na_koniec(view)
            assert view._root == str(kat)
            assert view.lbl_volume.text() == i18n.t("pipeline.volume_unset")
            assert view._thread is None
        finally:
            view.close()


# ---------- BP-7: nic po teście nie zostaje przy życiu ----------

_ZOSTAWIONY = []


def test_bp7_a_test_zostawia_okno_najwyzszego_poziomu(qapp):
    w = QWidget()
    w.show()
    _ZOSTAWIONY.append(w)              # mocna referencja: bez sprzątacza okno przeżyłoby test


def test_bp7_b_okno_z_poprzedniego_testu_zostalo_skasowane(qapp):
    """Autouse-sprzątacz (`conftest._skasuj_okna_testu`) kasuje okna najwyższego poziomu po teście:
    inaczej każda zmiana motywu przepolerowuje całą hałdę (BP-7: 55-69 s na jednym teście motywu).
    Zależy od kolejności plików (A przed B); bez A - pomija."""
    if not _ZOSTAWIONY:
        pytest.skip("test A nie biegł")
    import shiboken6
    assert not shiboken6.isValid(_ZOSTAWIONY[0])
