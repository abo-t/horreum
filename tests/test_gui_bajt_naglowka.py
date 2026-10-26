"""Wiersz Porządków „Nagłówek z bajtem spoza ASCII” i perspektywa w Zbiorach (AR-299) - szew rdzeń →
GUI na PRAWDZIWYM rdzeniu: skan pliku z bajtem zeznaje marker kopii (0046), `resolver.review_state`
liczy kubełek, `TasksView` mówi liczbę, a klik prowadzi do perspektywy, która czyta ten sam predykat.
Kopie niezbadane (wiersze sprzed 0046) wiersz mówi „?” i prowadzi do Dostawy.

`importorskip` na poziomie modułu - bez PySide6 plik się pomija."""
import pytest

pytest.importorskip("PySide6")

from horreum import db, repo, resolver, scan
from horreum.gui import i18n
from horreum.gui.app import STRONA_DOSTAWA, STRONA_ZBIORY, MainWindow
from horreum.gui.tasks import PRESET_HEADER_NONPRINTABLE, _TASKS, _liczniki_osi

from test_scan import _fits_z_bajtem

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

NOW = "2026-10-21T12:00:00+00:00"
KLUCZ = "header_nonprintable_frames"


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _pola_inline(monkeypatch):
    """Pokrycie pól Zbiorów inline (jak `test_gui_mainwindow`) - wynik z wątku tła nie wpada
    w środek asercji."""
    monkeypatch.setattr(MainWindow, "_pola_poza_watkiem", False)


def _wiersz(win):
    """(pozycja, człon drugi) wiersza zadania po kluczu (UserRole)."""
    from horreum.gui import rows
    lista = win.tasks_view.tasks
    for i in range(lista.count()):
        it = lista.item(i)
        if it.data(Qt.UserRole) == KLUCZ:
            return it, it.data(rows.SECONDARY)
    raise AssertionError(f"brak wiersza {KLUCZ!r}")


def _baza_z_bajtem(tmp_path):
    """Baza z jedną kopią FITS z bajtem 0xE9 w karcie, wciągniętą skanem (zbadana) → `(ścieżka, fid)`."""
    path = str(tmp_path / "b.db")
    con = db.open_db(path)
    p = _fits_z_bajtem(tmp_path / "ARCH" / "a.fits", 0xE9)
    scan.ingest_record(con, scan.scan_file(str(p)), volume="V", now=NOW, summary=scan.ScanSummary())
    fid = con.execute("SELECT frame_id FROM location").fetchone()[0]
    con.close()
    return path, fid


def test_wiersz_porzadkow_liczy_predykat_i_prowadzi_do_perspektywy(qapp, tmp_path):
    """AR-299: wiersz „Nagłówek z bajtem spoza ASCII” = długość zbioru właściciela predykatu
    (`resolver.nonprintable_frame_ids`), pogrubiony (robota), z podpowiedzią z katalogu; klik → Zbiory
    z perspektywą `PRESET_HEADER_NONPRINTABLE`, której lista to dokładnie ta klatka.
    Falsyfikatory: licznik z `0` na sztywno → „0”; trim spoza `_TRIMY` → lista bez zawężenia."""
    from horreum.gui import rows
    path, fid = _baza_z_bajtem(tmp_path)
    con = db.open_db(path)
    assert _liczniki_osi(con)[KLUCZ] == len(resolver.nonprintable_frame_ids(con)) == 1
    assert KLUCZ in [k for k, _l, _a in _TASKS]
    con.close()
    win = MainWindow(path)
    try:
        win.tasks_view.refresh_counts()
        it, liczba = _wiersz(win)
        assert liczba == "1  ›" and it.data(rows.STRONG) is True
        assert "bajt spoza drukowalnego ASCII" in it.toolTip()
        win.tasks_view.tasks.itemClicked.emit(it)
        assert win.stack.currentIndex() == STRONA_ZBIORY
        assert win.grid_view.combo_persp.currentData() == ("preset", PRESET_HEADER_NONPRINTABLE)
        assert win.grid_view._only_header_nonprintable is True
        assert set(win.grid_view._frame_ids) == {fid}
    finally:
        win.close()


def test_kopie_niezbadane_wiersz_mowi_pytajnik_i_prowadzi_do_dostawy(qapp, tmp_path):
    """AR-299 (0046): kopia FITS z odciskiem, ale bez zbadania surowych bajtów (wiersz sprzed migracji)
    - wiersz mówi „? · 1 kopia niesprawdzona”, nie „0” (zero byłoby fałszywym „czysto”), podpowiedź
    nazywa etap Dostawy, a klik w „?” prowadzi do Dostawy.
    Falsyfikator: gałąź niezbadanych zdjęta → „0  ›”."""
    path = str(tmp_path / "n.db")
    con = db.open_db(path)
    fid, _ = repo.upsert_frame(con, sha1_data="s", kind="light", filetype="fits", camera_id=None,
                               now=NOW)
    repo.add_location(con, frame_id=fid, volume="V", path="X:\\L\\a.fits", header_hash="h", now=NOW)
    assert resolver.review_state(con).header_nonprintable_unread == 1
    con.close()
    win = MainWindow(path)
    try:
        win.tasks_view.refresh_counts()
        it, liczba = _wiersz(win)
        assert liczba == "? · 1 kopia niesprawdzona  ›", liczba
        assert i18n.t("pipeline.btn.copy_bytes", n=1) in it.toolTip(), it.toolTip()
        win.tasks_view.tasks.itemClicked.emit(it)
        assert win.stack.currentIndex() == STRONA_DOSTAWA
    finally:
        win.close()
