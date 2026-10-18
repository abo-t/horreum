"""AR-231: przegląd śladów cofnięcia bez werdyktu przy montażu Porządków (`TasksView`). Wątek tła
(`_przeglad_watek`) i timer odczytu (`_przeglad_timer`) startują wyłącznie przy śladach bez werdyktu;
zamknięcie okna i zmiana bazy NIE czekają na przegląd zawieszony na `stat`; resztka martwej próby trafia
do wiersza „Kopie zostawione do oka” bez dotyku lokacji; porażka przeglądu stoi w wierszu pasywnym
z ponowieniem, a przycisk ponowienia gaśnie do wyniku. Rdzeń przeglądu:
`test_writeback_cofniecie_atomowe.py` (blok AR-231)."""
import threading
import time

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from horreum import repo, scan, writeback  # noqa: E402
from horreum.gui import i18n, queries  # noqa: E402
from test_writeback_inplace import NOW, _baza_z_plikiem, _fits  # noqa: E402

_WATEK = "horreum-przeglad-sladow"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _baza_ze_sladem(tmp_path, *, z_kopia=True):
    """Baza w pliku (`h.db`) z commitem drogą atomową i śladem cofnięcia bez werdyktu; `z_kopia` - kopia
    wyparta K martwej próby leży obok ścieżki. `(con, nazwy K/Z/T, frame_id)`."""
    p = _fits(tmp_path / "a.fits")
    con, loc = _baza_z_plikiem(tmp_path, p)
    assert len(writeback.commit(con, "R", now=NOW).applied) == 1
    b = con.execute("SELECT id FROM header_backups").fetchone()[0]
    s = "a" * 40
    k, t = str(p) + ".0000abcd.horreum-kopia", str(tmp_path / "tmp1.tmp")
    repo.record_atomic_undo(con, backup_id=b, result_sha1=s, result_size=1, result_hash=s,
                            byte_exact=True, source_sha1=s, source_size=1, displaced_path=k,
                            prepared_path=t, now=NOW)
    if z_kopia:
        with open(k, "wb") as fh:
            fh.write(b"K" * 64)
    return con, writeback._nazwy_sladu(k, t), loc["frame_id"]


def _czekaj(warunek, opis, limit=15.0):
    """Warunek po pętli zdarzeń (`processEvents` + `sleep`) - jeden `processEvents` mierzyłby fikcję."""
    koniec = time.monotonic() + limit
    while not warunek():
        if time.monotonic() > koniec:
            raise AssertionError(f"nie doczekano: {opis}")
        QApplication.processEvents()
        time.sleep(0.02)


def _widok(con):
    from horreum.gui.tasks import TasksView
    return TasksView(con, now_fn=lambda: NOW)


def _zwolnij(widok, con):
    widok.zatrzymaj_pola()
    widok.close()
    con.close()


def test_montaz_Porzadkow_przeglada_slady_w_tle(qapp, tmp_path):
    """Montaż Porządków przy śladzie bez werdyktu: wątek przeglądu i timer stoją od razu, po wyniku ślad
    ma `kept` (wiersz „Kopie zostawione do oka” bez dotyku lokacji), wiersz porażki schowany, a widok
    zleca rachunek liczników w tle (plakietka). Falsyfikator: start przeglądu zdjęty z `__init__`."""
    con, nazwy, fid = _baza_ze_sladem(tmp_path)
    widok = _widok(con)
    try:
        assert widok._przeglad_watek is not None and widok._przeglad_timer is not None
        assert widok._przeglad_timer.isActive()
        rachunki = []
        widok.refresh_counts = lambda **kw: rachunki.append(kw)
        _czekaj(lambda: widok._przeglad_watek is None, "wynik przeglądu")
        assert queries.kept_copy_frame_ids(con) == {fid}
        assert queries.tasks_state(con)["kept_copy_frames"] == 1
        assert widok.wiersz_sladow.isHidden() and not widok._przeglad_timer.isActive()
        assert rachunki == [{"w_tle": True}], rachunki
    finally:
        _zwolnij(widok, con)


def test_bez_sladow_przeglad_nie_startuje(qapp, tmp_path):
    """Baza bez śladów bez werdyktu (jeden SELECT przy montażu): ani wątku przeglądu, ani timera.
    Falsyfikator: przegląd startowany bezwarunkowo."""
    con, _loc = _baza_z_plikiem(tmp_path, _fits(tmp_path / "a.fits"))
    widok = _widok(con)
    try:
        assert widok._przeglad_watek is None and widok._przeglad_timer is None
    finally:
        _zwolnij(widok, con)


def test_zatrzymanie_przy_zawieszonym_stat_wraca_od_razu(qapp, tmp_path, monkeypatch):
    """Zerwany udział: `scan.path_gone` (prawdziwy szew rdzenia przeglądu) wisi na nazwach śladu.
    Zmiana bazy (`MainWindow._mount_views` → `_clear_views` → `zatrzymaj_pola`) i zamknięcie okna
    wracają bez czekania na przegląd; wątki kończą same po zwolnieniu `stat`.

    PRÓG 3 s: montaż buduje komplet widoków (Dostawa, Zbiory, Porządki, Planer, Dom) na maszynie
    współdzielonej z innymi bateriami - 0,5 s bywałoby fikcyjną czerwienią. Mutant (`join` wątku albo
    `QThread.wait()` w zatrzymaniu) czeka do limitu zawieszenia (20 s) - daleko nad progiem.
    Falsyfikator: zatrzymanie, które czeka na przegląd."""
    from horreum.gui.app import MainWindow
    monkeypatch.setattr(MainWindow, "_pola_poza_watkiem", False)
    con, nazwy, _fid = _baza_ze_sladem(tmp_path)
    con.close()
    zwolnij, wszedl = threading.Event(), threading.Event()
    prawdziwa = scan.path_gone

    def _wisi(x):
        if x in nazwy:
            wszedl.set()
            zwolnij.wait(20)
        return prawdziwa(x)
    monkeypatch.setattr(scan, "path_gone", _wisi)
    win = MainWindow(str(tmp_path / "h.db"))
    try:
        assert wszedl.wait(10), "przegląd nie doszedł do stat"
        t0 = time.perf_counter()
        win._mount_views()
        zmiana_bazy = time.perf_counter() - t0
        t0 = time.perf_counter()
        win.close()
        zamkniecie = time.perf_counter() - t0
        assert zmiana_bazy < 3.0 and zamkniecie < 3.0, (zmiana_bazy, zamkniecie)
    finally:
        zwolnij.set()
        for t in threading.enumerate():
            if t.name == _WATEK:
                t.join(30)
                assert not t.is_alive(), "wątek przeglądu nie skończył po zwolnieniu stat"


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_awaria_przegladu_stan_pasywny_i_ponow(qapp, tmp_path, monkeypatch, lang):
    """Zapis werdyktu pada prawdziwym `SQLITE_BUSY`: wiersz pasywny nad listą mówi zdaniem klasy błędu
    (`db_busy`) w języku UI, szczegół systemu pod kursorem, bez okna; „Ponów sprawdzenie” (prawdziwy klik)
    gaśnie od kliknięcia do wyniku, a udane ponowienie chowa wiersz i stawia `kept`.
    Falsyfikatory: porażka połknięta (wiersz schowany); przycisk aktywny w biegu ponowienia."""
    from test_writeback_cofniecie_atomowe import _prawdziwy_blad_zajetej_bazy
    con, _nazwy, fid = _baza_ze_sladem(tmp_path)
    zajeta = _prawdziwy_blad_zajetej_bazy(tmp_path)
    prawdziwa = repo.settle_atomic_undo

    def _pada(*a, **kw):
        raise zajeta
    monkeypatch.setattr(repo, "settle_atomic_undo", _pada)
    i18n.set_lang(lang)
    widok = _widok(con)
    try:
        widok.show()
        _czekaj(lambda: widok._przeglad_watek is None, "wynik przeglądu")
        assert not widok.wiersz_sladow.isHidden()
        tekst = widok.blad_sladow.text()
        assert tekst.startswith(i18n.t("tasks.traces_failed", msg="")), tekst
        assert i18n.t("objchg.item.db_busy", db_code="SQLITE_BUSY") in tekst, tekst
        assert "database is locked" in widok.blad_sladow.szczegol(), widok.blad_sladow.szczegol()
        assert widok.ponow_slady.isEnabled() and queries.kept_copy_frame_ids(con) == set()
        wolno = threading.Event()

        def _czeka(*a, **kw):
            wolno.wait(10)
            return prawdziwa(*a, **kw)
        monkeypatch.setattr(repo, "settle_atomic_undo", _czeka)
        QTest.mouseClick(widok.ponow_slady, Qt.LeftButton)
        assert not widok.ponow_slady.isEnabled(), "ponowienie w biegu - przycisk zgaszony"
        wolno.set()
        _czekaj(lambda: widok._przeglad_watek is None, "wynik ponowienia")
        assert widok.wiersz_sladow.isHidden() and widok.ponow_slady.isEnabled()
        assert queries.kept_copy_frame_ids(con) == {fid}
    finally:
        i18n.set_lang("pl")
        _zwolnij(widok, con)


@pytest.mark.parametrize("watek", ["baza_wraca", "baza_dalej_zablokowana"])
def test_baza_zablokowana_przy_montazu_nie_wywraca_widoku(qapp, tmp_path, monkeypatch, watek):
    """Zapytanie montażu „czy są ślady” pada prawdziwym `SQLITE_BUSY` (baza zablokowana ponad
    `busy_timeout`): widok się buduje, a „nie wiem, czy są ślady” zleca przegląd, który sam rozstrzyga -
    baza wróciła → `kept`; dalej zablokowana → wiersz pasywny ze zdaniem klasy `db_busy`.
    Falsyfikator: zapytanie montażu bez ochrony → wyjątek z `__init__` (`_mount_views` pada)."""
    from test_writeback_cofniecie_atomowe import _prawdziwy_blad_zajetej_bazy
    con, _nazwy, fid = _baza_ze_sladem(tmp_path)
    zajeta = _prawdziwy_blad_zajetej_bazy(tmp_path)
    prawdziwe = repo.unsettled_atomic_undos
    wolania = []

    def _zablokowana(*a, **kw):
        wolania.append(1)
        if len(wolania) == 1 or watek == "baza_dalej_zablokowana":
            raise zajeta
        return prawdziwe(*a, **kw)
    monkeypatch.setattr(repo, "unsettled_atomic_undos", _zablokowana)
    widok = _widok(con)
    try:
        assert widok._przeglad_watek is not None, "„nie wiem” zleca przegląd"
        _czekaj(lambda: widok._przeglad_watek is None, "wynik przeglądu")
        if watek == "baza_wraca":
            assert widok.wiersz_sladow.isHidden()
            assert queries.kept_copy_frame_ids(con) == {fid}
        else:
            assert not widok.wiersz_sladow.isHidden()
            assert i18n.t("objchg.item.db_busy", db_code="SQLITE_BUSY") in widok.blad_sladow.text()
    finally:
        _zwolnij(widok, con)


def test_blad_programu_w_zapytaniu_montazu_leci_dalej(qapp, tmp_path, monkeypatch):
    """Błąd spoza klas bazy (operacja na zamkniętym połączeniu - `ProgrammingError`) w zapytaniu montażu
    to błąd programu, nie „nie wiem”: leci z `__init__` (EXPECT). Falsyfikator: ochrona łapiąca każdy
    `sqlite3.Error`."""
    import sqlite3
    from horreum.gui.tasks import TasksView
    con, _nazwy, _fid = _baza_ze_sladem(tmp_path)

    def _zamkniete(*a, **kw):
        raise sqlite3.ProgrammingError("Cannot operate on a closed database.")
    monkeypatch.setattr(repo, "unsettled_atomic_undos", _zamkniete)
    try:
        with pytest.raises(sqlite3.ProgrammingError):
            TasksView(con, now_fn=lambda: NOW)
    finally:
        con.close()
